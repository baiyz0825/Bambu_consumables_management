"""中间盘 end 段裁剪测试。"""

from __future__ import annotations

from plate_merger.models import StartEndPolicy
from plate_merger.splitter import contains_swap_code, should_drop, trim_epilogue

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
