"""生成「不加热、不耗料」的换盘测试文件。

用途：调试换盘机构时，需要一个**能真实执行换盘动作**、但不升温、不出料的 3MF。

做法：拿一份真实切片文件当壳，只保留

    启动段（中和加热） → 换盘码 × N → 结束标记

并把所有加热目标置 0、删除等待升温指令，避免浪费时间与耗材。
元数据同步把时长与用量置 0，Studio 不会显示虚假消耗。
"""

from __future__ import annotations

import re
from pathlib import Path

from .errors import ValidationError
from .gcode import GcodeBlocks, detect_newline
from .io3mf import ThreeMfPackage, compute_md5, write_3mf
from .merger import build_swap_block
from .metadata import (
    MERGED_GCODE_MEMBER,
    rewrite_model_settings,
    rewrite_slice_info,
    strip_extra_plate_assets,
)
from .models import MergeOptions
from .swapcode import estimate_duration_s
from .thumbnail import render_swap_thumbnail
from .verifier import verify_package

#: 等待升温指令：会阻塞，必须整体删除
_WAIT_HEAT = re.compile(r"^M(109|190)\b")
#: 设置温度指令：改为 0
_SET_HEAT = re.compile(r"^(M104|M140)\s+S\d+")
#: CONFIG 段里的耗材声明注释：Studio 会据此要求耗材映射，测试文件必须清掉
_FILAMENT_META = re.compile(r"^;\s*(?:default_)?filament_\w+\s*=")

#: 空的 3D 模型（合法 3MF core XML、无任何几何）：保留引用完整性，去掉模板几何
_EMPTY_MODEL_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<model unit="millimeter" xml:lang="en-US" '
    'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">\n'
    ' <metadata name="Application">consumables-management swap-test</metadata>\n'
    " <resources/>\n <build/>\n</model>\n"
)

#: 包级引用：只指向空模型与文件缩略图
_PACKAGE_RELS_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Target="/3D/3dmodel.model" Id="rel-1" '
    'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
    '<Relationship Target="{thumbnail_target}" Id="rel-2" '
    'Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail"/>'
    "</Relationships>"
)

#: model_settings 引用：只指向合并后的 gcode
_MODEL_SETTINGS_RELS_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Target="/{gcode_member}" Id="rel-1" '
    'Type="http://schemas.bambulab.com/package/2021/gcode"/>'
    "</Relationships>"
)

#: 空的盘信息：无对象、无耗材
_EMPTY_PLATE_JSON = (
    '{"bbox_all":[0,0,0,0],"bbox_objects":[],"bed_type":"textured_plate",'
    '"filament_colors":[],"filament_ids":[],"first_extruder":0,'
    '"is_seq_print":false,"nozzle_diameter":0.4000000059604645,"version":2}'
)


def neutralize_heating(text: str, *, newline: str = "\n") -> str:
    """把加热目标置 0、删除等待升温指令，并剥离耗材声明注释。"""
    output: list[str] = []
    for line in text.splitlines(keepends=True):
        code = line.strip()
        if not code or code.startswith(";"):
            # 耗材声明（; filament_colour = ... 等）会让 Studio 认为切片
            # 依赖多种耗材并弹「未映射」警告——纯换盘测试不带耗材
            if _FILAMENT_META.match(code):
                continue
            output.append(line)
            continue
        if _WAIT_HEAT.match(code):
            continue
        match = _SET_HEAT.match(code)
        if match:
            output.append(f"{match.group(1)} S0{newline}")
            continue
        output.append(line)
    return "".join(output)


def build_tool_file(
    template: str | Path,
    *,
    cycles: int = 1,
    options: MergeOptions | None = None,
    output: str | Path | None = None,
) -> Path:
    """基于真实切片文件生成换盘测试 3MF。

    :param template: 任意已切片 3MF（建议用最终要打印的那份的同类文件）。
    :param cycles: 换盘次数；总动作数为 ``cycles`` 次换盘。
    :param options: 合盘配置，决定使用哪一档换盘码。
    :param output: 输出路径。
    :raises ValidationError: 模板不是已切片文件，或循环次数非法。
    """
    effective = options or MergeOptions()
    if cycles < 1:
        raise ValidationError("换盘次数必须 >= 1", detail={"cycles": cycles})

    with ThreeMfPackage.open(template) as package:
        gcodes = dict(package.plate_gcodes())
        if not gcodes:
            raise ValidationError("模板不是已切片 3MF", detail={"template": str(template)})

        member = gcodes[min(gcodes)]
        blocks = GcodeBlocks.parse(package.read_text(member))
        members = {name: package.read(name) for name in package.names}

    newline = detect_newline(blocks.preamble)
    preamble = neutralize_heating(blocks.preamble, newline=newline)

    # 每个换盘块对应「第 idx+1 盘结束 → 即将进入第 idx+2 盘」，
    # M117 盘号随块递增，实机验证时屏幕进度与实际换盘次数一致。
    # 块尾注入 M73：屏幕进度条按换盘次数均分推进（打印主体被丢弃，
    # 若不注入，进度条会一直停在 0%），R 按「剩余换盘次数 × 单次时长」估算。
    swap_total_s = estimate_duration_s(effective.swap_params) + max(effective.wait_after_swap_s, 0)
    swap_blocks = ""
    for idx in range(cycles):
        block = build_swap_block(
            effective,
            plate_index=idx + 1,
            total_plates=cycles + 1,
            newline=newline,
        )
        pct = round((idx + 1) / (cycles + 1) * 100)
        remain_min = max(round((cycles - idx - 1) * swap_total_s / 60), 0)
        swap_blocks += block + f"M73 P{pct} R{remain_min}{newline}"

    # 只保留一个 END 标记，结构才合法
    text = f"{preamble}{swap_blocks}{blocks.executable_end_marker}{blocks.epilogue}"

    members["Metadata/slice_info.config"] = rewrite_slice_info(
        members["Metadata/slice_info.config"].decode("utf-8"),
        prediction_s=0,
        weight_g=0,
        filaments=[],
    ).encode("utf-8")

    key = next(
        (name for name in members if name.lower() == "metadata/model_settings.config"), None
    )
    if key is not None:
        members[key] = rewrite_model_settings(
            members[key].decode("utf-8"), gcode_member=MERGED_GCODE_MEMBER
        ).encode("utf-8")

    strip_extra_plate_assets(members, keep=1)

    # 纯换盘测试不带耗材与模板残留：多盘耗材序列、辅助图片全部移除，
    # 否则 Studio 会按残留信息弹「耗材未映射」警告或显示无关预览图
    members.pop("Metadata/filament_sequence.json", None)
    for name in [n for n in members if n.startswith("Auxiliaries/")]:
        members.pop(name, None)

    # —— 彻底纯化：不掺杂任何模板的模型/图片/多盘引用 ——
    # 1) 移除模板的所有预览图与切割信息（预览换成本模块生成的文字缩略图）
    for name in [
        n
        for n in members
        if n.endswith(".png") or n == "Metadata/cut_information.xml"
    ]:
        members.pop(name, None)
    thumbnail = render_swap_thumbnail(cycles)
    members["Metadata/plate_1.png"] = thumbnail
    members["Metadata/plate_1_small.png"] = render_swap_thumbnail(cycles, size=128)

    # 2) 3D 模型替换为空资源（保留成员与引用完整性，去掉模板几何）；
    #    plate_1.json 清空对象列表，Studio 不再显示模板里的对象
    members["3D/3dmodel.model"] = _EMPTY_MODEL_XML.encode("utf-8")
    members["_rels/.rels"] = _PACKAGE_RELS_XML.format(thumbnail_target="/Auxiliaries/.thumbnails/thumbnail_3mf.png").encode("utf-8")
    members["Auxiliaries/.thumbnails/thumbnail_3mf.png"] = thumbnail
    members["Metadata/_rels/model_settings.config.rels"] = _MODEL_SETTINGS_RELS_XML.format(
        gcode_member=MERGED_GCODE_MEMBER
    ).encode("utf-8")
    plate_json_key = next((n for n in members if n.endswith("plate_1.json")), None)
    if plate_json_key:
        members[plate_json_key] = _EMPTY_PLATE_JSON

    gcode_bytes = text.encode("utf-8")
    members[MERGED_GCODE_MEMBER] = gcode_bytes
    members[f"{MERGED_GCODE_MEMBER}.md5"] = compute_md5(gcode_bytes, upper=True).encode("ascii")

    target = Path(output or "swap-test.gcode.3mf")
    write_3mf(target, members, opc_pack=effective.opc_pack)

    with ThreeMfPackage.open(target) as package:
        report = verify_package(
            package,
            expected_swap_count=cycles,
            swap_flag=effective.swap_start_flag,
        )
    report.raise_if_failed()

    return target
