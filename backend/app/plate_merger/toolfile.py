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
from .verifier import verify_package

#: 等待升温指令：会阻塞，必须整体删除
_WAIT_HEAT = re.compile(r"^M(109|190)\b")
#: 设置温度指令：改为 0
_SET_HEAT = re.compile(r"^(M104|M140)\s+S\d+")


def neutralize_heating(text: str, *, newline: str = "\n") -> str:
    """把加热目标置 0 并删除等待升温指令。"""
    output: list[str] = []
    for line in text.splitlines(keepends=True):
        code = line.strip()
        if not code or code.startswith(";"):
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

    swap_block = build_swap_block(
        effective,
        plate_index=1,
        total_plates=cycles + 1,
        newline=newline,
    )

    # 只保留一个 END 标记，结构才合法
    text = f"{preamble}{swap_block * cycles}{blocks.executable_end_marker}{blocks.epilogue}"

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
