"""生成「不加热、不耗料」的换盘测试文件。

用途：调试换盘机构时，需要一个**能真实执行换盘动作**、但不升温、不出料的 3MF。

做法：拿一份真实切片文件当壳，只保留

    启动段（中和加热） → 换盘码 × N → 结束标记

并把所有加热目标置 0、删除等待升温指令，避免浪费时间与耗材。
元数据同步把时长与用量置 0，Studio 不会显示虚假消耗。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from xml.etree import ElementTree as _ET

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


def _add_empty_filament(slice_info_xml: str) -> str:
    """在 slice_info 的 plate 下补一条空耗材，并把 filament_maps 收敛为单槽。

    对齐官方换盘测试文件：``<filament id="1" type="" color="" used_m="0" used_g="0"/>``。
    没有这条时 Studio 会认为切片引用了耗材却无元数据，弹「未映射」并禁用发送。
    """
    root = _ET.fromstring(slice_info_xml)
    plate = root.find("plate")
    if plate is None:
        return slice_info_xml

    for metadata in plate.findall("metadata"):
        if metadata.get("key") in {"filament_maps", "limit_filament_maps"}:
            metadata.set("value", "1" if metadata.get("key") == "filament_maps" else "0")

    for existing in plate.findall("filament"):
        plate.remove(existing)
    _ET.SubElement(
        plate,
        "filament",
        {
            "id": "1",
            "tray_info_idx": "",
            "type": "",
            "color": "",
            "used_m": "0",
            "used_g": "0",
        },
    )
    return _ET.tostring(root, encoding="unicode", xml_declaration=False)


def _collapse_filament_maps(model_settings_xml: str) -> str:
    """把 model_settings 的 ``filament_maps`` 收敛为单槽 ``"1"``。"""
    return re.sub(
        r'(key="filament_maps"\s+value=")[^"]*(")',
        r"\g<1>1\g<2>",
        model_settings_xml,
    )


def _collapse_filament_settings(project_settings_json: str) -> str:
    """工程设置里的 ``filament_*`` 数组收敛为 1 项（与单槽一致）。

    这些数组按槽位定义耗材（颜色 / 类型 / 预设 ID…），多盘模板会留 5 项，
    Studio 发送时会要求 5 个耗材映射——纯换盘测试只应有一个占位耗材。
    """
    try:
        data = json.loads(project_settings_json)
    except ValueError:
        return project_settings_json

    if not isinstance(data, dict):
        return project_settings_json

    changed = False
    for key, value in data.items():
        if key.startswith("filament_") and isinstance(value, list) and len(value) > 1:
            data[key] = value[:1]
            changed = True

    return json.dumps(data, ensure_ascii=False) if changed else project_settings_json


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

    # 先按合盘语义清空并置 0，再补一个「空耗材」条目：
    # 官方换盘测试文件正是 1 条空 filament（type/color 为空、用量 0）——
    # 完全清空会让 Studio 认为「切片引用了耗材但无元数据」而禁用发送。
    slice_info = rewrite_slice_info(
        members["Metadata/slice_info.config"].decode("utf-8"),
        prediction_s=0,
        weight_g=0,
        filaments=[],
    )
    members["Metadata/slice_info.config"] = _add_empty_filament(slice_info).encode("utf-8")

    key = next(
        (name for name in members if name.lower() == "metadata/model_settings.config"), None
    )
    if key is not None:
        collapsed = rewrite_model_settings(
            members[key].decode("utf-8"), gcode_member=MERGED_GCODE_MEMBER
        )
        members[key] = _collapse_filament_maps(collapsed).encode("utf-8")

    # 工程设置里的耗材数组按槽位定义（多盘模板会有 5 项），Studio 据此要求
    # 5 个耗材映射。纯测试文件收敛为单槽，与官方换盘测试文件一致。
    settings_key = next(
        (name for name in members if name.lower() == "metadata/project_settings.config"), None
    )
    if settings_key is not None:
        members[settings_key] = _collapse_filament_settings(
            members[settings_key].decode("utf-8")
        ).encode("utf-8")

    strip_extra_plate_assets(members, keep=1)

    # 纯换盘测试不带耗材与模板残留：多盘耗材序列、辅助图片全部移除，
    # 否则 Studio 会按残留信息弹「耗材未映射」警告或显示无关预览图
    members.pop("Metadata/filament_sequence.json", None)
    for name in [n for n in members if n.startswith("Auxiliaries/")]:
        members.pop(name, None)

    # 预览图换成文字缩略图（一点 = 一次换盘）。
    # 注意：其余模板资产（3D 几何、rels、plate json）必须原样保留——
    # 实测替换/删除它们会让 Studio 判定「3mf 文件配置无效」。
    if "Metadata/plate_1.png" in members:
        members["Metadata/plate_1.png"] = render_swap_thumbnail(cycles, size=512)
    if "Metadata/plate_1_small.png" in members:
        members["Metadata/plate_1_small.png"] = render_swap_thumbnail(cycles, size=128)

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
