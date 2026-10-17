"""合盘流水线：把多个已切片盘组装成一个可下发的 ``.gcode.3mf``。

流程：

1. 打开每个输入 3MF，确认是 plate-sliced 格式；
2. 解析所选盘的元信息与 G-code 三段结构；
3. 建立全局耗材方案（跨盘去重 + 槽位映射）；
4. 拼接 G-code 并注入换盘码；
5. 以第一个输入为基底，重写元数据、替换 G-code、删除多余盘资源；
6. 按 OPC 规范打包并校验。

设计说明：基底取**第一个输入**（继承其 ``project_settings`` / ``3dmodel`` / 缩略图），
这与旧「数据重组」App 的做法一致；但它意味着所有输入应使用同一版本、同一工艺预设切片。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .errors import UnsupportedFormatError, ValidationError
from .filament import build_plan
from .gcode import GcodeBlocks, detect_newline
from .io3mf import ThreeMfPackage, compute_md5, write_3mf
from .merger import PlateSegment, merge_segments
from .metadata import (
    MERGED_GCODE_MEMBER,
    rewrite_filament_sequence,
    rewrite_model_settings,
    rewrite_plate_json,
    rewrite_slice_info,
)
from .models import (
    InputPlate,
    MergeOptions,
    MergeResult,
    MergeWarning,
    PlateInfo,
)
from .sliceinfo import parse_slice_info
from .verifier import verify_package

#: 指向第 N 盘的资源，合盘后只保留第 1 盘
_PLATE_ASSET_PATTERN = re.compile(
    r"^Metadata/(?:plate_(\d+)\.(?:gcode|gcode\.md5|png|json)|plate_no_light_(\d+)\.png|top_(\d+)\.png|pick_(\d+)\.png)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MergeRequest:
    """一条合盘输入：某个 3MF 中的某个盘。"""

    source: Path
    plate_index: int = 1


def _collect_inputs(requests: Sequence[MergeRequest]) -> tuple[list[InputPlate], dict[str, bytes], list[str]]:
    """读取所有输入，返回（盘信息列表、基底成员、G-code 文本列表）。"""
    if not requests:
        raise ValidationError("没有输入盘")

    infos: list[InputPlate] = []
    gcode_texts: list[str] = []
    base_members: dict[str, bytes] | None = None
    warnings: list[str] = []

    for position, request in enumerate(requests, start=1):
        with ThreeMfPackage.open(request.source) as package:
            if not package.is_plate_sliced():
                raise UnsupportedFormatError(
                    "输入不是已切片 3MF",
                    detail={"source": str(request.source)},
                )

            gcodes = dict(package.plate_gcodes())
            member = gcodes.get(request.plate_index)
            if member is None:
                raise ValidationError(
                    "指定的盘不存在",
                    detail={"source": str(request.source), "plate": request.plate_index, "available": sorted(gcodes)},
                )

            text = package.read_text(member)
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
                bed_type=None,
            )
            infos.append(InputPlate(source=request.source, plate=info))
            gcode_texts.append(text)

    versions = {info.plate.client_version for info in infos if info.plate.client_version}
    if len(versions) > 1:
        warnings.append(f"输入使用了多个切片器版本：{sorted(versions)}，元数据可能不一致")

    if base_members is None:
        raise ValidationError("没有可用的基底 3MF")

    return infos, base_members, gcode_texts


def _strip_extra_plate_assets(members: dict[str, bytes]) -> None:
    """删除第 2 盘及以后的所有资源，只保留第 1 盘。"""
    for name in list(members):
        match = _PLATE_ASSET_PATTERN.match(name)
        if not match:
            continue
        number = next((group for group in match.groups() if group), None)
        if number is not None and int(number) != 1:
            del members[name]


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
    :raises ValidationError: 输入非法或校验失败。
    """
    effective = options or MergeOptions()
    infos, members, gcode_texts = _collect_inputs(requests)
    warning_messages: list[str] = []

    plan = build_plan([info.plate for info in infos])
    warning_messages.extend(warning.message for warning in plan.warnings)

    segments = [
        PlateSegment(
            index=info.plate.index,
            blocks=GcodeBlocks.parse(text),
            mapping=plan.mapping_for(info.plate.index),
        )
        for info, text in zip(infos, gcode_texts)
    ]

    newline = detect_newline(gcode_texts[0])
    outcome = merge_segments(segments, options=effective, newline=newline)

    # ---- 元数据重写（全部基于基底文件）
    members["Metadata/slice_info.config"] = rewrite_slice_info(
        members["Metadata/slice_info.config"].decode("utf-8"),
        prediction_s=sum(info.plate.prediction_s or 0 for info in infos) or None,
        weight_g=sum(info.plate.weight_g or 0.0 for info in infos) or None,
        filaments=[item.ref for item in plan.filaments],
    ).encode("utf-8")

    members["Metadata/model_settings.config"] = rewrite_model_settings(
        members["Metadata/model_settings.config"].decode("utf-8"),
        gcode_member=MERGED_GCODE_MEMBER,
    ).encode("utf-8")

    if "Metadata/filament_sequence.json" in members:
        members["Metadata/filament_sequence.json"] = rewrite_filament_sequence(
            members["Metadata/filament_sequence.json"].decode("utf-8"),
            slots=plan.slot_count,
        ).encode("utf-8")

    if "Metadata/plate_1.json" in members:
        members["Metadata/plate_1.json"] = rewrite_plate_json(
            members["Metadata/plate_1.json"].decode("utf-8"),
            filaments=[item.ref for item in plan.filaments],
        ).encode("utf-8")

    # ---- 替换 G-code 与 md5
    gcode_bytes = outcome.text.encode("utf-8")
    members[MERGED_GCODE_MEMBER] = gcode_bytes
    members[f"{MERGED_GCODE_MEMBER}.md5"] = compute_md5(gcode_bytes, upper=True).encode("ascii")

    _strip_extra_plate_assets(members)

    target = Path(output or effective.output_name or "merged.gcode.3mf")
    write_3mf(target, members, opc_pack=effective.opc_pack)

    # ---- 校验
    with ThreeMfPackage.open(target) as package:
        report = verify_package(package, expected_swap_count=outcome.swap_count)
    report.raise_if_failed()

    return MergeResult(
        output_path=target,
        plate_count=outcome.plate_count,
        gcode_bytes=len(gcode_bytes),
        total_time_s=sum(info.plate.prediction_s or 0 for info in infos) or None,
        total_weight_g=round(sum(info.plate.weight_g or 0.0 for info in infos), 2) or None,
        md5=compute_md5(gcode_bytes, upper=True),
        warnings=tuple(MergeWarning(code="merge", message=message) for message in warning_messages),
    )
