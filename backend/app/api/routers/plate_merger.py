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

import asyncio
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.models.merged_artifact import MergedArtifact
from app.db.models.printer import Printer

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
from app.plate_merger.layers import LayerIndex
from app.plate_merger.models import PlateInfo
from app.plate_merger.planner import PlateJob
from app.plate_merger.presets import EDITABLE_FIELDS, resolve_preset

router = APIRouter(prefix="/plate-merger", tags=["plate-merger"])

#: 数据根目录：设了 ``PLATE_MERGER_DATA_DIR`` 就收进去（Docker 里挂卷持久化）；
#: 未设置时保持 /tmp 下的历史位置，本地开发与旧部署零破坏
_PM_DATA_DIR = os.environ.get("PLATE_MERGER_DATA_DIR")
#: 生成产物统一落在这里，下载接口只允许读取该目录
_OUTPUT_DIR = Path(_PM_DATA_DIR, "outputs") if _PM_DATA_DIR else Path(tempfile.gettempdir()) / "plate-merger"
#: 上传的原始 3MF；API 只允许从这里读取输入，杜绝任意路径读取
_UPLOAD_DIR = Path(_PM_DATA_DIR, "uploads") if _PM_DATA_DIR else Path(tempfile.gettempdir()) / "plate-merger-uploads"
#: 单文件上限（3MF 常见 10~200MB）
_MAX_UPLOAD_BYTES = 512 * 1024 * 1024


def _require_3mf(path_str: str) -> Path:
    """校验输入路径：必须位于上传目录内，且为 ``.3mf``。

    API 不接受任意路径，避免通过 ``path`` 参数读取主机上的任意文件；
    CLI 与单测直接调用 ``app.plate_merger``，不受此限制。
    """
    path = Path(path_str).expanduser().resolve()
    if path.parent != _UPLOAD_DIR.resolve():
        raise HTTPException(
            status_code=400,
            detail="路径非法：请先调用 /plate-merger/upload 上传文件",
        )
    if not path.is_file():
        raise HTTPException(status_code=400, detail=f"文件不存在：{path.name}")
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
    #: 覆盖预设中的可调参数（字段见 GET /presets/{id}/params 的 editable）
    swap_overrides: dict[str, float | int | bool] | None = None
    #: 自定义乐谱行（pre_sound / post_sound 取 custom 时必填）
    pre_custom_notes: list[str] | None = None
    post_custom_notes: list[str] | None = None


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
    #: 可选：关联的合盘产物记录，下发成功后更新其状态
    artifact_id: str | None = None


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


@router.post("/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    """上传 3MF 到服务端，返回后续接口（analyze / merge / probe）可用的 path。"""
    original = Path(file.filename or "").name
    if not original.lower().endswith(".3mf"):
        raise HTTPException(status_code=400, detail="只接受 .3mf 文件")

    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^\w.\-]", "_", original)
    target = _UPLOAD_DIR / f"{uuid4().hex[:8]}-{safe_name}"

    size = 0
    try:
        with target.open("wb") as handle:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > _MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="文件超过 512MB 上限")
                handle.write(chunk)
    except HTTPException:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    return {"path": str(target), "name": original, "size": size}


def _artifact_to_dict(artifact: MergedArtifact) -> dict:
    """artifact ORM → API 字典。"""
    return {
        "id": str(artifact.id),
        "file_name": artifact.file_name,
        "file_path": artifact.file_path,
        "file_size": artifact.file_size,
        "md5": artifact.md5,
        "plate_count": artifact.plate_count,
        "total_time_s": artifact.total_time_s,
        "total_weight_g": artifact.total_weight_g,
        "filaments": artifact.filaments_json,
        "sources": artifact.sources_json,
        "options": artifact.options_json,
        "status": artifact.status,
        "printer_id": str(artifact.printer_id) if artifact.printer_id else None,
        "job_id": str(artifact.job_id) if artifact.job_id else None,
        "dispatched_at": artifact.dispatched_at.isoformat() if artifact.dispatched_at else None,
        "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
        "exists": (_OUTPUT_DIR / artifact.file_name).is_file(),
        "download_url": f"/plate-merger/download/{artifact.file_name}",
    }


@router.get("/artifacts")
async def list_artifacts(
    limit: int = 100,
    printer_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """合盘产物记录（含耗材清单与下发状态），按创建时间倒序。

    ``printer_id`` 用于设备详情页自动匹配「当前这台机器在打哪个产物」。
    """
    stmt = select(MergedArtifact)
    if printer_id:
        try:
            stmt = stmt.where(MergedArtifact.printer_id == UUID(printer_id))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="printer_id 格式错误") from exc
    stmt = stmt.order_by(MergedArtifact.created_at.desc()).limit(limit)

    rows = (await db.execute(stmt)).scalars().all()
    return [_artifact_to_dict(item) for item in rows]


#: 层索引缓存：合盘产物不可变，按文件名缓存（单份约 0.5MB）
_LAYER_CACHE: dict[str, dict] = {}
_LAYER_CACHE_LIMIT = 3


def _build_layer_payload(path: Path) -> dict:
    """解析产物里的 G-code 并生成层索引（阻塞，调用方负责放线程池）。"""
    with ThreeMfPackage.open(path) as package:
        members = sorted(
            name
            for name in package.names
            if name.startswith("Metadata/plate_") and name.endswith(".gcode")
        )
        if not members:
            raise ValueError("产物中未找到 G-code")
        gcode = package.read_text_lossy(members[0])

    index = LayerIndex.build(gcode)

    # 换盘段含推盘 / 擦嘴的大位移（Y 可达 264+），会把某层 bbox 撑到床外。
    # 这类层沿用上一层的 bbox：既保证层号与 layer_num 对齐，又不让喷嘴飞出模型。
    lo, hi = -64.0, 320.0
    rows: list[list[float]] = []
    previous: tuple[float, float, float, float] | None = None
    fallback = 0
    for item in index.layers:
        box = (item.x_min, item.x_max, item.y_min, item.y_max)
        if all(lo <= value <= hi for value in box):
            previous = box
        else:
            fallback += 1
            box = previous or (0.0, 0.0, 0.0, 0.0)
        rows.append([round(item.z_mm, 3), *(round(value, 2) for value in box)])

    # 顶层 bbox 用修正后的层重算，避免把越界层的 1316 透出去
    bbox = (
        (
            min(row[1] for row in rows),
            max(row[2] for row in rows),
            min(row[3] for row in rows),
            max(row[4] for row in rows),
        )
        if rows
        else None
    )
    return {
        "count": len(rows),
        "bbox": list(bbox) if bbox else None,
        "out_of_bounds": fallback,
        "layers": rows,
    }


@router.get("/artifacts/{artifact_id}/layers")
async def get_artifact_layers(artifact_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    """返回产物的逐层 Z 与 XY 包围盒，供数字孪生推算喷嘴位置。

    每行固定为 ``[z, x_min, x_max, y_min, y_max]``。用数组而非对象，
    是为了把 1 万层的体积压到约 500KB（对象格式会翻倍）。
    """
    artifact = await db.get(MergedArtifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="产物不存在")

    cached = _LAYER_CACHE.get(artifact.file_name)
    if cached is not None:
        return {"file_name": artifact.file_name, **cached}

    path = _OUTPUT_DIR / artifact.file_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="产物文件已不存在")

    try:
        payload = await asyncio.to_thread(_build_layer_payload, path)
    except Exception as exc:  # noqa: BLE001 - 解析失败原因需要原样透出
        raise HTTPException(status_code=422, detail=f"解析 G-code 失败：{exc}") from exc

    if len(_LAYER_CACHE) >= _LAYER_CACHE_LIMIT:
        _LAYER_CACHE.pop(next(iter(_LAYER_CACHE)))
    _LAYER_CACHE[artifact.file_name] = payload
    return {"file_name": artifact.file_name, **payload}


@router.get("/outputs")
async def list_outputs(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """列出磁盘上的产物文件；有对应记录时附带 ``artifact`` 元数据。"""
    if not _OUTPUT_DIR.is_dir():
        return []

    rows = (await db.execute(select(MergedArtifact))).scalars().all()
    by_name = {item.file_name: item for item in rows}

    entries: list[dict] = []
    for path in _OUTPUT_DIR.iterdir():
        if not path.is_file() or path.suffix.lower() != ".3mf":
            continue
        stat = path.stat()
        entry: dict = {"name": path.name, "size": stat.st_size, "mtime": stat.st_mtime}
        artifact = by_name.get(path.name)
        if artifact is not None:
            entry["artifact"] = _artifact_to_dict(artifact)
        entries.append(entry)

    entries.sort(key=lambda item: item["mtime"], reverse=True)
    for item in entries:
        item["download_url"] = f"/plate-merger/download/{item['name']}"
    return entries


@router.delete("/outputs/{name}")
def delete_output(name: str) -> dict:
    """删除一个产物文件。"""
    if name in {"", ".", ".."} or "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="非法文件名")

    target = _OUTPUT_DIR / name
    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    target.unlink()
    return {"deleted": name}


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


@router.get("/presets/{preset_id}/params")
def preset_params(preset_id: str) -> dict:
    """返回预设的可编辑参数与当前值，供前端渲染参数面板。

    只暴露「数值与开关」——动作顺序由渲染器固定、不开放编辑，
    因为顺序本身即机械语义，改错会撞机。
    """
    try:
        preset = get_preset(preset_id)
    except PlateMergerError as exc:
        raise _fail(exc) from exc

    editable = []
    for key, label in EDITABLE_FIELDS.items():
        value = getattr(preset, key)
        if isinstance(value, bool):
            kind = "bool"
        elif isinstance(value, float):
            kind = "float"
        else:
            kind = "int"
        editable.append({"key": key, "label": label, "value": value, "type": kind})

    return {
        "preset_id": preset.preset_id,
        "name": preset.name,
        "machine": preset.machine,
        "approach_mode": preset.approach_mode.value,
        "y_limit": preset.y_limit,
        "editable": editable,
        "note": "换盘动作顺序不可编辑；这些参数只影响停留时间、行程与推盘方式。",
    }


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
async def merge_endpoint(payload: MergeIn, db: AsyncSession = Depends(get_db)) -> dict:
    """执行合盘，产物写入临时目录，并登记到 ``merged_artifacts``。

    登记是「产物 → 下发 → 任务 → 扣料」链路的起点：没有这条记录，
    系统只知道磁盘上多了个文件，不知道它是一次生产。
    """
    # 先读元数据：既用于全局槽位统计，也用于写产物记录
    infos = _load_plate_infos(payload.items)

    try:
        requests = [
            MergeRequest(source=_require_3mf(item.path), plate_index=item.plate)
            for item in payload.items
        ]
        options = MergeOptions(
            swap_params=resolve_preset(payload.preset, payload.swap_overrides),
            start_end_policy=StartEndPolicy(payload.policy),
            plate_display=PlateDisplay(payload.plate_display),
            pre_change_sound=AudioMode(payload.pre_sound),
            post_change_sound=AudioMode(payload.post_sound),
            pre_custom_notes=tuple(payload.pre_custom_notes) if payload.pre_custom_notes else None,
            post_custom_notes=tuple(payload.post_custom_notes) if payload.post_custom_notes else None,
            hotbed_cooldown_c=payload.cooldown,
            wait_after_swap_s=payload.wait_s,
            output_name=payload.output_name,
        )
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output = _OUTPUT_DIR / (payload.output_name or "merged.gcode.3mf")
        # 合盘是 CPU 密集操作：放线程池，避免阻塞事件循环
        result = await asyncio.to_thread(merge_packages, requests, options=options, output=output)
    except PlateMergerError as exc:
        raise _fail(exc) from exc

    plan = build_plan(infos)
    filaments = [
        {
            "slot": item.slot,
            "type": item.type,
            "color": item.color,
            "total_used_g": item.total_used_g,
            "plates": list(item.plate_indexes),
        }
        for item in plan.filaments
    ]
    sources = [
        {
            "name": Path(item.path).name,
            "plate": item.plate,
            "time_s": info.prediction_s,
            "weight_g": info.weight_g,
        }
        for item, info in zip(payload.items, infos)
    ]

    file_name = result.output_path.name
    now = datetime.now(timezone.utc)

    # 同名产物允许覆盖：复用记录并重置下发状态
    artifact = (
        await db.execute(select(MergedArtifact).where(MergedArtifact.file_name == file_name))
    ).scalar_one_or_none()
    if artifact is None:
        artifact = MergedArtifact(file_name=file_name, file_path=str(result.output_path), created_at=now)
        db.add(artifact)

    artifact.file_path = str(result.output_path)
    artifact.file_size = result.output_path.stat().st_size
    artifact.md5 = result.md5
    artifact.plate_count = result.plate_count
    artifact.total_time_s = result.total_time_s
    artifact.total_weight_g = result.total_weight_g
    artifact.filaments_json = filaments
    artifact.sources_json = sources
    artifact.options_json = {
        "preset": payload.preset,
        "policy": payload.policy,
        "plate_display": payload.plate_display,
        "pre_sound": payload.pre_sound,
        "post_sound": payload.post_sound,
        "cooldown": payload.cooldown,
        "wait_s": payload.wait_s,
    }
    artifact.status = "draft"
    artifact.printer_id = None
    artifact.job_id = None
    artifact.dispatched_at = None
    artifact.updated_at = now

    await db.commit()

    return {
        "artifact_id": str(artifact.id),
        "output": file_name,
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


async def _mark_dispatched(db: AsyncSession, payload: DispatchIn, path: Path) -> None:
    """下发成功后更新产物记录；失败不影响下发结果返回。"""
    try:
        artifact = None
        if payload.artifact_id:
            try:
                artifact = await db.get(MergedArtifact, UUID(payload.artifact_id))
            except (ValueError, TypeError):
                artifact = None
        if artifact is None:
            artifact = (
                await db.execute(
                    select(MergedArtifact).where(MergedArtifact.file_name == path.name)
                )
            ).scalar_one_or_none()
        if artifact is None:
            return

        printer = (
            await db.execute(select(Printer).where(Printer.serial == payload.serial))
        ).scalar_one_or_none()

        now = datetime.now(timezone.utc)
        artifact.status = "dispatched"
        artifact.printer_id = printer.id if printer else None
        artifact.dispatched_at = now
        artifact.updated_at = now
        await db.commit()
    except Exception:
        # 记录失败不能影响「已经成功下发」这个事实
        await db.rollback()


@router.post("/dispatch")
async def dispatch_endpoint(payload: DispatchIn, db: AsyncSession = Depends(get_db)) -> dict:
    """下发打印（需要可选依赖 ``paho-mqtt``）。"""
    path = _require_3mf(payload.path)
    try:
        target = PrinterTarget(
            host=payload.host,
            access_code=payload.access_code,
            serial=payload.serial,
        )
        result = await asyncio.to_thread(
            dispatch,
            path,
            target,
            use_ams=payload.use_ams,
            ams_mapping=payload.ams_mapping,
            wait_s=payload.wait_s,
        )
    except PlateMergerError as exc:
        raise _fail(exc) from exc

    if result.accepted:
        await _mark_dispatched(db, payload, path)

    return {"accepted": result.accepted, "detail": result.detail, "remote_name": result.remote_name}
