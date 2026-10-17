"""换盘码渲染测试：以硬件配套的 0623 基准文件做指令级回归比对。"""

from __future__ import annotations

from pathlib import Path

import pytest

from plate_merger.errors import SwapCodeError
from plate_merger.models import ApproachMode, SwapParams
from plate_merger.presets import BALANCED, CONSERVATIVE, FAST, get_preset, list_presets
from plate_merger.swapcode import estimate_duration_s, render_swap_code, validate_params

_FIXTURE = Path(__file__).parent / "fixtures" / "0623-code.gcode"


def _instructions(text: str) -> list[str]:
    """提取有效指令：去掉空行、注释行与行尾分号。"""
    result: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        stripped = line.rstrip(";").strip()
        if stripped:
            result.append(stripped)
    return result


def test_conservative_matches_reference_instructions() -> None:
    """保守档渲染结果必须与硬件配套的原始换盘码逐条一致。"""
    reference = _instructions(_FIXTURE.read_text(encoding="utf-8"))
    generated = _instructions(render_swap_code(CONSERVATIVE))

    assert generated == reference


def test_render_is_pure() -> None:
    assert render_swap_code(CONSERVATIVE) == render_swap_code(CONSERVATIVE)


def test_render_has_start_and_end_flags() -> None:
    code = render_swap_code(CONSERVATIVE)

    assert code.startswith(";start change plate")
    assert code.rstrip().endswith(";end change plate")


def test_relative_and_absolute_modes_are_balanced() -> None:
    instructions = _instructions(render_swap_code(CONSERVATIVE))

    assert instructions.count("G91") == instructions.count("G90")


def test_fast_preset_skips_initial_homing_and_uses_open_loop() -> None:
    instructions = _instructions(render_swap_code(FAST))
    code = render_swap_code(FAST)

    # 第一条指令不应是归零（保守档会先 G28 Y）
    assert instructions[0] != "G28 Y"
    assert "G1 Y260 F3000" in code
    assert "G380 S1 Y260" not in code


def test_validate_rejects_shallow_eject_offset() -> None:
    params = SwapParams(eject_offset=0.0)

    issues = validate_params(params)

    assert any("卸盘越位量" in issue for issue in issues)
    with pytest.raises(SwapCodeError):
        render_swap_code(params)


def test_validate_rejects_target_beyond_travel() -> None:
    issues = validate_params(SwapParams(approach_target=300.0))

    assert any("超出 Y 行程" in issue for issue in issues)


def test_validate_rejects_mismatched_shake_lengths() -> None:
    params = SwapParams(shake_offsets=(1.0, 2.0), retract_feedrates=(20000,))

    issues = validate_params(params)

    assert any("数量不一致" in issue for issue in issues)


def test_duration_estimation_is_positive_and_fast_is_quicker() -> None:
    conservative = estimate_duration_s(CONSERVATIVE)
    fast = estimate_duration_s(FAST)

    assert conservative > 0
    assert fast < conservative


def test_presets_are_addressable() -> None:
    assert get_preset(CONSERVATIVE.preset_id) is CONSERVATIVE
    assert len(list_presets()) == 3

    with pytest.raises(SwapCodeError):
        get_preset("not-exist")


def test_balanced_preset_keeps_force_mode_but_shortens_dwell() -> None:
    assert BALANCED.approach_mode is ApproachMode.FORCE
    assert BALANCED.dwell_after_z_ms < CONSERVATIVE.dwell_after_z_ms
