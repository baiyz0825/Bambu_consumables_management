"""合盘流水线：把多个已切片盘组装成一个可下发的 ``.gcode.3mf``。

流程：

1. 打开每个输入 3MF，确认是 plate-sliced 格式且**尚未包含换盘码**；
2. 解析所选盘的元信息与 G-code 三段结构；
3. 建立全局耗材方案（跨盘去重 + 槽位映射）；
4. 拼接 G-code 并注入换盘码；
5. 以第一个输入为基底，重写元数据、替换 G-code、删除多余盘资源；
6. 按 OPC 规范打包并校验，**校验失败会删除产物**，避免坏包被误拿去打印。

设计说明：基底取**第一个输入**（继承其 ``project_settings`` / ``3dmodel`` / 缩略图），
这与旧「数据重组」App 的做法一致；但它意味着所有输入应使用同一版本、同一工艺预设切片。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .errors import MetadataError, PlateMergerError, UnsupportedFormatError, ValidationError
from .filament import build_plan
from .gcode import GcodeBlocks, detect_newline
from .io3mf import ThreeMfPackage, compute_md5, write_3mf
from .merger import PlateSegment, merge_segments
from .metadata import (
    MERGED_GCODE_MEMBER,
    rewrite_filament_sequence,
    rewrite_model_settings,
    rewrite_plate_json,
    rewrite_project_settings,
    rewrite_slice_info,
    strip_extra_plate_assets,
)
from .models import InputPlate, MergeOptions, MergeResult, MergeWarning, PlateInfo
from .sliceinfo import parse_slice_info
from .splitter import contains_swap_code
from .verifier import verify_package

#: 合盘必需的元数据成员
_REQUIRED_MEMBERS = (
    "Metadata/slice_info.config",
    "Metadata/model_settings.config",
)


@dataclass(frozen=True)
class MergeRequest:
    """一条合盘输入：某个 3MF 中的某个盘。"""

    source: Path
    plate_index: int = 1


def _get_member(members: dict[str, bytes], name: str) -> tuple[str, bytes]:
    """按大小写不敏感的方式取成员，返回（实际键名, 内容）。

    :raises MetadataError: 成员缺失。
    """
    if name in members:
        return name, members[name]
    lowered = {key.lower(): key for key in members}
    actual = lowered.get(name.lower())
    if actual is None:
        raise MetadataError("3MF 缺少必需成员", detail={"member": name})
    return actual, members[actual]


def _collect_inputs(
    requests: Sequence[MergeRequest],
    *,
    swap_flag: str,
) -> tuple[list[InputPlate], dict[str, bytes], list[str], list[MergeWarning]]:
    """读取所有输入。

    :return: （盘信息列表、基底成员、G-code 文本列表、告警列表）
    :raises UnsupportedFormatError: 输入不是已切片格式。
    :raises ValidationError: 盘不存在、输入已含换盘码。
    """
    if not requests:
        raise ValidationError("没有输入盘")

    infos: list[InputPlate] = []
    gcode_texts: list[str] = []
    base_members: dict[str, bytes] | None = None
    warnings: list[MergeWarning] = []

    for position, request in enumerate(requests, start=1):
        with ThreeMfPackage.open(request.source) as package:
            if not package.is_plate_sliced():
                raise UnsupportedFormatError("输入不是已切片 3MF", detail={"source": str(request.source)})

            gcodes = dict(package.plate_gcodes())
            member = gcodes.get(request.plate_index)
            if member is None:
                raise ValidationError(
                    "指定的盘不存在",
                    detail={
                        "source": str(request.source),
                        "plate": request.plate_index,
                        "available": sorted(gcodes),
                    },
                )

            text = package.read_text(member)
            if contains_swap_code(text, swap_flag):
                raise ValidationError(
                    "输入已包含换盘码，请使用原始切片文件",
                    detail={"source": str(request.source), "plate": request.plate_index},
                )

            slice_info = parse_slice_info(package.read_text("Metadata/slice_info.config"))
            slice_plate = slice_info.plate(request.plate_index)
            if slice_plate is None:
                raise ValidationError(
                    "slice_info 中缺少对应盘",
                    detail={"source": str(request.source), "plate": request.plate_index},
                )

            if position == 1:
                base_members = {name: package.read(name) for name in package.names}

            # 用「全局顺序号」作为盘号，避免不同文件里同为 plate_1 造成映射冲突
            info = PlateInfo(
                index=position,
                gcode_member=member,
                prediction_s=slice_plate.prediction_s,
                weight_g=slice_plate.weight_g,
                filaments=slice_plate.filaments,
                client_version=slice_info.header.client_version,
            )
            infos.append(InputPlate(source=request.source, plate=info))
            gcode_texts.append(text)

    versions = {info.plate.client_version for info in infos if info.plate.client_version}
    if len(versions) > 1:
        warnings.append(
            MergeWarning(
                code="slicer_version_mismatch",
                message=f"输入使用了多个切片器版本：{sorted(versions)}，元数据可能不一致",
            )
        )

    if base_members is None:
        raise ValidationError("没有可用的基底 3MF")

    return infos, base_members, gcode_texts, warnings


def _strip_extra_plate_assets(members: dict[str, bytes]) -> None:
    """删除第 2 盘及以后的所有资源，只保留第 1 盘。"""
    strip_extra_plate_assets(members, keep=1)


def _rewrite_metadata(
    members: dict[str, bytes],
    *,
    infos: Sequence[InputPlate],
    plan_filaments: Sequence,
    gcode_member: str = MERGED_GCODE_MEMBER,
) -> None:
    """就地重写全部元数据成员。"""
    for required in _REQUIRED_MEMBERS:
        _get_member(members, required)

    key, raw = _get_member(members, "Metadata/slice_info.config")
    members[key] = rewrite_slice_info(
        raw.decode("utf-8"),
        prediction_s=sum(info.plate.prediction_s or 0 for info in infos) or None,
        weight_g=sum(info.plate.weight_g or 0.0 for info in infos) or None,
        filaments=plan_filaments,
    ).encode("utf-8")

    key, raw = _get_member(members, "Metadata/model_settings.config")
    members[key] = rewrite_model_settings(raw.decode("utf-8"), gcode_member=gcode_member).encode("utf-8")

    sequence_key = next((name for name in members if name.lower() == "metadata/filament_sequence.json"), None)
    if sequence_key is not None:
        members[sequence_key] = rewrite_filament_sequence(
            members[sequence_key].decode("utf-8"),
            slots=len(plan_filaments),
        ).encode("utf-8")

    plate_json_key = next((name for name in members if name.lower() == "metadata/plate_1.json"), None)
    if plate_json_key is not None:
        members[plate_json_key] = rewrite_plate_json(
            members[plate_json_key].decode("utf-8"),
            filaments=[item.ref for item in plan_filaments],
        ).encode("utf-8")

    # 基底只对应第一个盘的耗材数，必须按全局槽位扩展，否则 Studio 只显示 1 个槽
    project_key = next(
        (name for name in members if name.lower() == "metadata/project_settings.config"), None
    )
    if project_key is not None:
        members[project_key] = rewrite_project_settings(
            members[project_key].decode("utf-8"),
            filaments=plan_filaments,
        ).encode("utf-8")


def merge(
    requests: Sequence[MergeRequest],
    *,
    options: MergeOptions | None = None,
    output: str | Path | None = None,
) -> MergeResult:
    """执行完整合盘。

    :param requests: 按打印顺序排列的输入盘。
    :param options: 合盘配置，``None`` 时使用默认值（保守换盘码 + SLIM 裁剪）。
    :param output: 输出路径；``None`` 时使用 ``options.output_name`` 或 ``merged.gcode.3mf``。
    :raises PlateMergerError: 输入非法或校验失败（失败时会删除产物）。
    """
    effective = options or MergeOptions()
    infos, members, gcode_texts, warnings = _collect_inputs(
        requests, swap_flag=effective.swap_start_flag
    )

    plan = build_plan([info.plate for info in infos])

    segments = [
        PlateSegment(
            index=info.plate.index,
            blocks=GcodeBlocks.parse(text),
            mapping=plan.mapping_for(info.plate.index),
            prediction_s=info.plate.prediction_s,
        )
        for info, text in zip(infos, gcode_texts)
    ]

    newline = detect_newline(gcode_texts[0])
    outcome = merge_segments(segments, options=effective, newline=newline)

    _rewrite_metadata(members, infos=infos, plan_filaments=plan.filaments)

    gcode_bytes = outcome.text.encode("utf-8")
    members[MERGED_GCODE_MEMBER] = gcode_bytes
    md5 = compute_md5(gcode_bytes, upper=True)
    members[f"{MERGED_GCODE_MEMBER}.md5"] = md5.encode("ascii")

    _strip_extra_plate_assets(members)

    target = Path(output or effective.output_name or "merged.gcode.3mf")
    write_3mf(target, members, opc_pack=effective.opc_pack)

    try:
        with ThreeMfPackage.open(target) as package:
            report = verify_package(
                package,
                expected_swap_count=outcome.swap_count,
                swap_flag=effective.swap_start_flag,
            )
        report.raise_if_failed()
    except PlateMergerError:
        # 校验失败时不留下坏包，避免用户误拿去打印
        target.unlink(missing_ok=True)
        raise

    return MergeResult(
        output_path=target,
        plate_count=outcome.plate_count,
        gcode_bytes=len(gcode_bytes),
        total_time_s=sum(info.plate.prediction_s or 0 for info in infos) or None,
        total_weight_g=round(sum(info.plate.weight_g or 0.0 for info in infos), 2) or None,
        md5=md5,
        warnings=tuple(warnings) + tuple(plan.warnings),
    )
