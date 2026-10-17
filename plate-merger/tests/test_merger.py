"""拼接测试：结构标记唯一性与片段顺序。"""

from __future__ import annotations

import pytest

from plate_merger.errors import ValidationError
from plate_merger.gcode import GcodeBlocks
from plate_merger.merger import PlateSegment, build_swap_block, merge_segments
from plate_merger.models import MergeOptions, StartEndPolicy
from plate_merger.presets import CONSERVATIVE

_END_SEQUENCE = (
    "M621 S255\n"
    "M104 S0 ; turn off hotend\n"
    "M400\n"
    "G1 Z50 F600\n"
    ";=====printer finish  sound=========\n"
    "M1006 W\n"
    "M18 X Y Z\n"
    "M73 P100 R0\n"
)


def _gcode(index: int) -> str:
    return (
        "; HEADER_BLOCK_START\n; HEADER_BLOCK_END\n"
        "; CONFIG_BLOCK_START\n; CONFIG_BLOCK_END\n"
        "; EXECUTABLE_BLOCK_START\n"
        f"G28\nG1 X{index} Y{index} F3000\nM620 S0A\nT1000\n"
        f"{_END_SEQUENCE}"
        "; EXECUTABLE_BLOCK_END\n"
    )


def _segments(count: int) -> list[PlateSegment]:
    return [
        PlateSegment(index=position, blocks=GcodeBlocks.parse(_gcode(position)), mapping={0: 0})
        for position in range(1, count + 1)
    ]


def test_swap_count_is_plate_count_minus_one() -> None:
    outcome = merge_segments(_segments(3), options=MergeOptions(swap_params=CONSERVATIVE))

    assert outcome.plate_count == 3
    assert outcome.swap_count == 2
    assert outcome.text.count(";start change plate") == 2


def test_only_one_executable_end_marker() -> None:
    """全文只能有一个 END 标记，否则二次合盘会在第一个 END 处截断。"""
    outcome = merge_segments(_segments(3), options=MergeOptions(swap_params=CONSERVATIVE))

    assert outcome.text.count("; EXECUTABLE_BLOCK_END") == 1
    assert outcome.text.count("; EXECUTABLE_BLOCK_START") == 1


def test_middle_plates_lose_shutdown_but_keep_retraction() -> None:
    outcome = merge_segments(_segments(3), options=MergeOptions(swap_params=CONSERVATIVE))

    # 3 盘：中间 2 盘的 M18 应被裁掉，只剩最后 1 个
    assert outcome.text.count("M18 X Y Z") == 1
    # 退料保留：3 盘各一次
    assert outcome.text.count("M621 S255") == 3
    # 抬 Z 必须保留（换盘前把喷嘴抬离零件）
    assert outcome.text.count("G1 Z50 F600") == 3


def test_preamble_only_from_first_plate() -> None:
    outcome = merge_segments(_segments(3), options=MergeOptions(swap_params=CONSERVATIVE))

    assert outcome.text.count("; HEADER_BLOCK_START") == 1


def test_epilogue_only_from_last_plate() -> None:
    """前两盘的结束音乐应被裁掉，仅最后一盘保留。"""
    outcome = merge_segments(_segments(2), options=MergeOptions(swap_params=CONSERVATIVE))

    assert outcome.text.count(";=====printer finish  sound") == 1


def test_swap_block_starts_with_motion_sync_and_absolute_mode() -> None:
    block = build_swap_block(MergeOptions(swap_params=CONSERVATIVE))

    assert "M400" in block
    assert "G90" in block
    assert block.index("M400") < block.index(";start change plate")


def test_empty_segments_rejected() -> None:
    with pytest.raises(ValidationError):
        merge_segments([], options=MergeOptions())


def test_crlf_is_preserved() -> None:
    gcode = _gcode(1).replace("\n", "\r\n")
    segments = [PlateSegment(index=1, blocks=GcodeBlocks.parse(gcode), mapping={0: 0})]

    outcome = merge_segments(segments, options=MergeOptions(swap_params=CONSERVATIVE))

    assert "\r\n" in outcome.text


def test_turbo_policy_drops_retraction() -> None:
    options = MergeOptions(swap_params=CONSERVATIVE, start_end_policy=StartEndPolicy.TURBO)
    outcome = merge_segments(_segments(2), options=options)

    # 中间盘退料被剥离，只剩最后一盘的 1 次
    assert outcome.text.count("M621 S255") == 1
