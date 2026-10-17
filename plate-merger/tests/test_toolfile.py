"""换盘测试文件生成器测试。"""

from __future__ import annotations

import re
import zipfile

import pytest

from _fixtures import make_3mf

from plate_merger.errors import ValidationError
from plate_merger.models import MergeOptions
from plate_merger.presets import CONSERVATIVE
from plate_merger.toolfile import build_tool_file, neutralize_heating


def test_neutralize_heating_zeroes_targets_and_drops_waits() -> None:
    text = "M104 S220\nM140 S60\nM109 S220\nM190 S60\nG28\n"

    result = neutralize_heating(text)

    assert "M104 S0" in result
    assert "M140 S0" in result
    assert "M109" not in result
    assert "M190" not in result
    assert "G28" in result


def test_tool_file_has_no_positive_temperature(tmp_path) -> None:
    template = make_3mf(tmp_path / "tpl.3mf", ["#F6DA5A", "#FFFFFF"])
    output = tmp_path / "swap-test.gcode.3mf"

    build_tool_file(template, cycles=2, options=MergeOptions(swap_params=CONSERVATIVE), output=output)

    with zipfile.ZipFile(output) as archive:
        gcode = archive.read("Metadata/plate_1.gcode").decode()

    # 必须按行判断：CONFIG 段内嵌的模板文本里会出现 ``M104 S220`` 这类字符串，
    # 但它们不是执行行，全文搜索会误报
    active_lines = [line.strip() for line in gcode.splitlines() if not line.strip().startswith(";")]
    assert not any(re.match(r"M(104|140)\s+S[1-9]", line) for line in active_lines)
    assert not any(re.match(r"M(109|190)\b", line) for line in active_lines)


def test_tool_file_contains_requested_swap_count(tmp_path) -> None:
    template = make_3mf(tmp_path / "tpl.3mf", ["#F6DA5A"])
    output = tmp_path / "swap-test.gcode.3mf"

    build_tool_file(template, cycles=3, options=MergeOptions(swap_params=CONSERVATIVE), output=output)

    with zipfile.ZipFile(output) as archive:
        gcode = archive.read("Metadata/plate_1.gcode").decode()

    assert gcode.count(";start change plate") == 3
    assert gcode.count("; EXECUTABLE_BLOCK_END") == 1


def test_tool_file_zeroes_usage_metadata(tmp_path) -> None:
    template = make_3mf(tmp_path / "tpl.3mf", ["#F6DA5A"])
    output = tmp_path / "swap-test.gcode.3mf"

    build_tool_file(template, cycles=1, options=MergeOptions(swap_params=CONSERVATIVE), output=output)

    with zipfile.ZipFile(output) as archive:
        slice_info = archive.read("Metadata/slice_info.config").decode()

    assert 'key="prediction" value="0"' in slice_info
    assert 'key="weight" value="0"' in slice_info


def test_invalid_cycles_rejected(tmp_path) -> None:
    template = make_3mf(tmp_path / "tpl.3mf", ["#F6DA5A"])

    with pytest.raises(ValidationError):
        build_tool_file(template, cycles=0, output=tmp_path / "x.gcode.3mf")
