"""G-code 三段块解析测试。"""

from __future__ import annotations

import pytest

from plate_merger.errors import MissingAnchorError
from plate_merger.gcode import (
    GcodeBlocks,
    count_occurrences,
    detect_newline,
    extract_header_block,
    find_all,
    locate_anchor,
)

_SAMPLE = (
    "; HEADER_BLOCK_START\n"
    "; model: demo\n"
    "; HEADER_BLOCK_END\n"
    "; CONFIG_BLOCK_START\n"
    "; layer_height = 0.2\n"
    "; EXECUTABLE_BLOCK_START\n"
    "G28\n"
    "G1 X10 Y10 F3000\n"
    "; EXECUTABLE_BLOCK_END\n"
    "; end note\n"
)


def test_parse_splits_three_sections() -> None:
    blocks = GcodeBlocks.parse(_SAMPLE)

    assert blocks.preamble.startswith("; HEADER_BLOCK_START")
    assert blocks.preamble.rstrip().endswith("EXECUTABLE_BLOCK_START")
    assert "G28" in blocks.executable
    assert blocks.epilogue.strip() == "; end note"


def test_render_restores_original() -> None:
    blocks = GcodeBlocks.parse(_SAMPLE)

    assert blocks.render() == _SAMPLE


def test_missing_start_raises() -> None:
    with pytest.raises(MissingAnchorError):
        GcodeBlocks.parse("G28\n")


def test_missing_end_raises() -> None:
    with pytest.raises(MissingAnchorError):
        GcodeBlocks.parse("; EXECUTABLE_BLOCK_START\nG28\n")


def test_executable_body_excludes_markers() -> None:
    blocks = GcodeBlocks.parse(_SAMPLE)

    assert blocks.executable_body == "G28\nG1 X10 Y10 F3000\n"


def test_preamble_line_count() -> None:
    blocks = GcodeBlocks.parse(_SAMPLE)

    assert blocks.preamble_line_count == 6


def test_detect_newline() -> None:
    assert detect_newline("a\r\nb") == "\r\n"
    assert detect_newline("a\nb") == "\n"


def test_count_and_find_all() -> None:
    text = "x;M;M;M"

    assert count_occurrences(text, ";M") == 3
    assert find_all(text, ";M") == [1, 3, 5]


def test_locate_anchor_first_and_last() -> None:
    text = ";flag\nA\n;flag\nB\n;flag\n"

    assert locate_anchor(text, ";flag", occurrence=0) == 0
    assert locate_anchor(text, ";flag", occurrence=-1) == 16


def test_locate_anchor_respects_range() -> None:
    text = ";flag\nA\n;flag\nB\n;flag\n"

    # 跳过第一个锚点后，首次出现位于偏移 8
    assert locate_anchor(text, ";flag", search_from=1, occurrence=0) == 8
    # 限定搜索区间后，只剩偏移 8 这一处
    assert locate_anchor(text, ";flag", search_from=1, search_to=10) == 8


def test_locate_anchor_optional_returns_minus_one() -> None:
    assert locate_anchor("nothing", ";flag", required=False) == -1


def test_locate_anchor_occurrence_out_of_range_raises() -> None:
    with pytest.raises(MissingAnchorError):
        locate_anchor(";flag\n", ";flag", occurrence=5)


def test_extract_header_block() -> None:
    header = extract_header_block(_SAMPLE)

    assert header is not None
    assert "model: demo" in header


def test_extract_header_block_absent() -> None:
    assert extract_header_block("G28\n") is None
