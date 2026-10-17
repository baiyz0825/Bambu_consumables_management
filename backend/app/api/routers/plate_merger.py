"""合盘工具 API（consumables-management 的生产模块）。

分层说明：

- **算法层** 在 ``app.plate_merger``：纯标准库、零外部依赖、可独立 CLI 与单测；
- **适配层** 即本文件：只做参数转换、路径校验与错误映射，不含业务逻辑。

安全约束：

1. 输入只接受已存在且后缀为 ``.3mf`` 的文件；
2. 输出固定写入临时目录，下载接口只接受纯文件名，杜绝路径穿越；
3. 本组端点不直接操作打印机（下发单独端点，凭据由调用方提供）。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.plate_merger import (
    AudioMode,
    MergeOptions,
    MergeRequest,
    PlateDisplay,
    PlateMergerError,
    PrinterTarget,
    StartEndPolicy,
    ThreeMfPackage,
    build_plan,
    build_tool_file,
    dispatch,
    estimate_duration_s,
    fingerprint_diff,
    get_preset,
    list_presets,
    merge as merge_packages,
    parse_slice_info,
    plan_plates,
    probe,
    render_swap_code,
    validate_params,
)
from app.plate_merger.models import PlateInfo
from app.plate_merger.planner import PlateJob

router = APIRouter(prefix="/plate-merger", tags=["plate-merger"])

#: 生成产物统一落在这里，下载接口只允许读取该目录
_OUTPUT_DIR = Path(tempfile.gettempdir()) / "plate-merger"


def _require_3mf(path_str: str) -> Path:
    """校验输入路径：必须存在且为 ``.3mf``。"""
    path = Path(path_str).expanduser()
    if not path.is_file():
        raise HTTPException(status_code=400, detail=f"文件不存在：{path}")
    if path.suffix.lower() != ".3mf":
        raise HTTPException(status_code=400, detail="只接受 .3mf 文件")
    return path


def _fail(exc: Exception) -> HTTPException:
    """把领域异常映射为 422。"""
    return HTTPException(status_code=422, detail=f"{getattr(exc, 'code', 'error')}: {exc}")


class ItemIn(BaseModel):
    """一条输入盘。"""

    path: str
    plate: int = Field(default=1, ge=1)


class AnalyzeIn(BaseModel):
    """统计请求。"""

    items: list[ItemIn]


class MergeIn(BaseModel):
    """合盘请求。"""

    items: list[ItemIn]
    preset: str = "builtin:a1-conservative"
    policy: str = "slim"
    plate_display: str = "off"
    pre_sound: str = "off"
    post_sound: str = "jingle"
    cooldown: int | None = None
    wait_s: int = Field(default=0, ge=0)
    output_name: str | None = None


class ProbeIn(BaseModel):
    """指纹请求。"""

    path: str


class DiffIn(BaseModel):
    """指纹对比请求。"""

    base: str
    current: str


class TestFileIn(BaseModel):
    """测试文件请求。"""

    template: str
    cycles: int = Field(default=1, ge=1, le=50)
    preset: str = "builtin:a1-conservative"


class PlanItemIn(BaseModel):
    """排产件。"""

    name: str
    minutes: int = Field(gt=0)
    filament: list[str] = Field(default_factory=list)


class PlanIn(BaseModel):
    """排产请求。"""

    jobs: list[PlanItemIn]
    max_minutes: int | None = Field(default=None, gt=0)
    max_plates: int = Field(default=9, ge=1)


class DispatchIn(BaseModel):
    """下发请求。"""

    path: str
    host: str
    access_code: str
    serial: str
    use_ams: bool = False
    ams_mapping: str = ""
    wait_s: float = Field(default=15.0, ge=1.0, le=120.0)


def _load_plate_infos(items: list[ItemIn]) -> list[PlateInfo]:
    """读取各盘的耗材信息（仅元数据，不读 G-code 正文）。"""
    infos: list[PlateInfo] = []
    for position, item in enumerate(items, start=1):
        path = _require_3mf(item.path)
        with ThreeMfPackage.open(path) as package:
            slice_info = parse_slice_info(package.read_text("Metadata/slice_info.config"))
            plate = slice_info.plate(item.plate)
            if plate is None:
                raise HTTPException(status_code=400, detail=f"{path.name} 缺少第 {item.plate} 盘")
            infos.append(
                PlateInfo(
                    index=position,
                    gcode_member=f"Metadata/plate_{item.plate}.gcode",
                    prediction_s=plate.prediction_s,
                    weight_g=plate.weight_g,
                    filaments=plate.filaments,
                    client_version=slice_info.header.client_version,
                )
            )
    return infos


@router.get("/presets")
def get_presets() -> list[dict]:
    """列出内置换盘码预设。"""
    return [
        {
            "id": preset.preset_id,
            "name": preset.name,
            "machine": preset.machine,
            "approach_mode": preset.approach_mode.value,
            "y_limit": preset.y_limit,
        }
        for preset in list_presets()
    ]


@router.post("/presets/{preset_id}/render")
def render_preset(preset_id: str) -> dict:
    """渲染换盘码，返回 G-code 与时长估算。"""
    try:
        preset = get_preset(preset_id)
    except PlateMergerError as exc:
        raise _fail(exc) from exc

    issues = validate_params(preset)
    if issues:
        raise HTTPException(status_code=422, detail={"issues": issues})
    return {"gcode": render_swap_code(preset), "duration_s": estimate_duration_s(preset)}


@router.post("/analyze")
def analyze(payload: AnalyzeIn) -> dict:
    """统计盘数、时长与耗材（不生成文件）。"""
    infos = _load_plate_infos(payload.items)
    plan = build_plan(infos)
    return {
        "plates": [
            {
                "index": info.index,
                "prediction_s": info.prediction_s,
                "weight_g": info.weight_g,
                "client_version": info.client_version,
                "filaments": [
                    {
                        "slot": ref.slot,
                        "type": ref.type,
                        "color": ref.color,
                        "used_g": ref.used_g,
                        "tray_info_idx": ref.tray_info_idx,
                    }
                    for ref in info.filaments
                ],
            }
            for info in infos
        ],
        "totals": {
            "plates": len(infos),
            "time_s": sum(info.prediction_s or 0 for info in infos),
            "weight_g": round(sum(info.weight_g or 0.0 for info in infos), 2),
        },
        "filaments": [
            {
                "slot": item.slot,
                "type": item.type,
                "color": item.color,
                "total_used_g": item.total_used_g,
                "plates": list(item.plate_indexes),
            }
            for item in plan.filaments
        ],
        "warnings": [{"code": w.code, "message": w.message} for w in plan.warnings],
    }


@router.post("/merge")
def merge_endpoint(payload: MergeIn) -> dict:
    """执行合盘，产物写入临时目录，用 ``/download`` 取回。"""
    try:
        requests = [
            MergeRequest(source=_require_3mf(item.path), plate_index=item.plate)
            for item in payload.items
        ]
        options = MergeOptions(
            swap_params=get_preset(payload.preset),
            start_end_policy=StartEndPolicy(payload.policy),
            plate_display=PlateDisplay(payload.plate_display),
            pre_change_sound=AudioMode(payload.pre_sound),
            post_change_sound=AudioMode(payload.post_sound),
            hotbed_cooldown_c=payload.cooldown,
            wait_after_swap_s=payload.wait_s,
            output_name=payload.output_name,
        )
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        result = merge_packages(
            requests,
            options=options,
            output=_OUTPUT_DIR / (payload.output_name or "merged.gcode.3mf"),
        )
    except PlateMergerError as exc:
        raise _fail(exc) from exc

    return {
        "output": result.output_path.name,
        "plate_count": result.plate_count,
        "gcode_bytes": result.gcode_bytes,
        "total_time_s": result.total_time_s,
        "total_weight_g": result.total_weight_g,
        "md5": result.md5,
        "warnings": [{"code": w.code, "message": w.message} for w in result.warnings],
    }


@router.get("/download/{name}")
def download(name: str) -> FileResponse:
    """下载合盘产物；只接受纯文件名。"""
    if name in {"", ".", ".."} or "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="非法文件名")

    target = _OUTPUT_DIR / name
    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(target, filename=name, media_type="application/octet-stream")


@router.post("/probe")
def probe_endpoint(payload: ProbeIn) -> dict:
    """探测切片产物的结构指纹。"""
    return probe(_require_3mf(payload.path)).to_dict()


@router.post("/probe/diff")
def probe_diff(payload: DiffIn) -> dict:
    """比较两份切片的指纹差异。"""
    changes = fingerprint_diff(probe(_require_3mf(payload.base)), probe(_require_3mf(payload.current)))
    return {"changes": list(changes)}


@router.post("/test-file")
def test_file_endpoint(payload: TestFileIn) -> dict:
    """生成不加热、不耗料的换盘测试文件。"""
    try:
        options = MergeOptions(swap_params=get_preset(payload.preset))
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        path = build_tool_file(
            _require_3mf(payload.template),
            cycles=payload.cycles,
            options=options,
            output=_OUTPUT_DIR / f"swap-test-{payload.cycles}.gcode.3mf",
        )
    except PlateMergerError as exc:
        raise _fail(exc) from exc
    return {"output": path.name, "cycles": payload.cycles}


@router.post("/plan")
def plan_endpoint(payload: PlanIn) -> dict:
    """自动分盘排产。"""
    jobs = [
        PlateJob(
            name=item.name,
            minutes=item.minutes,
            filament=tuple((item.filament + ["", "", ""])[:3]),
        )
        for item in payload.jobs
    ]
    try:
        result = plan_plates(jobs, max_minutes=payload.max_minutes, max_plates=payload.max_plates)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "plates": [
            {
                "index": plate.index,
                "minutes": plate.minutes,
                "count": plate.count,
                "filament": list(plate.filament) if plate.filament else None,
                "jobs": [{"name": job.name, "minutes": job.minutes} for job in plate.jobs],
            }
            for plate in result.plates
        ],
        "total_minutes": result.total_minutes,
        "warnings": [{"code": w.code, "message": w.message} for w in result.warnings],
    }


@router.post("/dispatch")
def dispatch_endpoint(payload: DispatchIn) -> dict:
    """下发打印（需要可选依赖 ``paho-mqtt``）。"""
    try:
        target = PrinterTarget(
            host=payload.host,
            access_code=payload.access_code,
            serial=payload.serial,
        )
        result = dispatch(
            _require_3mf(payload.path),
            target,
            use_ams=payload.use_ams,
            ams_mapping=payload.ams_mapping,
            wait_s=payload.wait_s,
        )
    except PlateMergerError as exc:
        raise _fail(exc) from exc

    return {"accepted": result.accepted, "detail": result.detail, "remote_name": result.remote_name}
