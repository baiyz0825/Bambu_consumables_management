"""中间盘 end 段裁剪测试。"""

from __future__ import annotations

import pytest

from app.plate_merger.errors import MissingAnchorError
from app.plate_merger.models import StartEndPolicy
from app.plate_merger.splitter import contains_swap_code, should_drop, trim_epilogue, trim_executable_tail

_EPILOGUE = (
    "; end of print\n"
    "M104 S0\n"
    "M140 S0\n"
    "M106 P1 S0\n"
    "G28 X Y\n"
    "M18\n"
    "M620 S255A\n"
    "T255\n"
    "M400\n"
)


def test_full_policy_keeps_everything() -> None:
    assert trim_epilogue(_EPILOGUE, StartEndPolicy.FULL) == _EPILOGUE


def test_slim_removes_heating_and_homing_but_keeps_unload() -> None:
    result = trim_epilogue(_EPILOGUE, StartEndPolicy.SLIM)

    assert "M104 S0" not in result
    assert "M140 S0" not in result
    assert "M106 P1 S0" not in result
    assert "G28 X Y" not in result
    assert "M18" not in result
    # 退料必须保留，避免喷嘴带料换盘
    assert "M620 S255A" in result
    assert "T255" in result


def test_turbo_also_removes_unload() -> None:
    result = trim_epilogue(_EPILOGUE, StartEndPolicy.TURBO)

    assert "M620 S255A" not in result
    assert "T255" not in result
    assert "M400" in result


def test_comments_and_nonzero_temperatures_are_kept() -> None:
    text = "; note\nM104 S220\nM140 S60\n"

    result = trim_epilogue(text, StartEndPolicy.SLIM)

    assert result == text


def test_should_drop_is_false_for_full_policy() -> None:
    assert should_drop("M104 S0", StartEndPolicy.FULL) is False
    assert should_drop("M104 S0", StartEndPolicy.SLIM) is True


def test_trim_handles_empty_text() -> None:
    assert trim_epilogue("", StartEndPolicy.SLIM) == ""


def test_contains_swap_code_detects_both_flags() -> None:
    english = ";start change plate\nG28 Y\n"
    chinese = ";开始换盘\nG28 Y\n"

    assert contains_swap_code(english, ";start change plate") is True
    assert contains_swap_code(chinese, ";start change plate") is False
    assert contains_swap_code(chinese, ";开始换盘", ";end change plate") is True


# ---- EXECUTABLE 尾部裁剪（合盘最关键的一步） ----

_TAIL = (
    "G1 X10\n"
    "M621 S255\n"
    "M104 S0 ; turn off hotend\n"
    "M400\n"
    "M17 Z0.4\n"
    "M18 X Y Z\n"
    "M73 P100 R0\n"
)


def test_trim_tail_slim_keeps_unload_but_drops_shutdown() -> None:
    result = trim_executable_tail(_TAIL, StartEndPolicy.SLIM)

    assert "M621 S255" in result
    assert "M104 S0" not in result
    assert "M18" not in result
    assert "M73 P100" not in result


def test_trim_tail_turbo_drops_unload_too() -> None:
    result = trim_executable_tail(_TAIL, StartEndPolicy.TURBO)

    assert "M621 S255" not in result
    assert "G1 X10" in result


def test_trim_tail_full_only_drops_power_off() -> None:
    result = trim_executable_tail(_TAIL, StartEndPolicy.FULL)

    assert "M621 S255" in result
    assert "M104 S0" in result
    assert "M18" not in result


def test_trim_tail_without_anchor_raises() -> None:
    """找不到结束序列属输入异常，必须报错而不是静默不裁剪。"""
    body = "G1 X10\nG1 Y20\n"

    with pytest.raises(MissingAnchorError):
        trim_executable_tail(body, StartEndPolicy.SLIM)


def test_trim_tail_full_without_anchor_is_unchanged() -> None:
    """FULL 档没有裁剪需求，无锚点时原样返回。"""
    body = "G1 X10\nG1 Y20\n"

    assert trim_executable_tail(body, StartEndPolicy.FULL) == body


def test_trim_tail_falls_back_to_hotend_off_anchor() -> None:
    body = "G1 X10\nM104 S0\nM18 X Y Z\n"

    result = trim_executable_tail(body, StartEndPolicy.SLIM)

    assert "M104 S0" in result
    assert "M18" not in result
