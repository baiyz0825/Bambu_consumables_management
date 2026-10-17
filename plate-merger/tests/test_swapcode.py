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


def test_relative_and_absolute_modes_are_properly_paired() -> None:
    """G91 与 G90 必须成对出现，且不得连续进入同一模式。"""
    mode = False  # G-code 默认绝对模式
    for instruction in _instructions(render_swap_code(CONSERVATIVE)):
        if instruction == "G91":
            assert mode is False, "出现连续 G91，说明上一次相对模式未闭合"
            mode = True
        elif instruction == "G90":
            assert mode is True, "出现孤立的 G90"
            mode = False
    assert mode is False, "结尾仍处于相对模式"


def test_render_supports_crlf() -> None:
    code = render_swap_code(CONSERVATIVE, newline="\r\n")

    assert "\r\n" in code
    assert _instructions(code) == _instructions(_FIXTURE.read_text(encoding="utf-8"))


def test_fast_preset_skips_initial_homing_and_uses_open_loop() -> None:
    instructions = _instructions(render_swap_code(FAST))
    code = render_swap_code(FAST)

    # 第一条指令不应是归零（保守档会先 G28 Y）
    assert instructions[0] != "G28 Y"
    assert "G1 Y260 F3000" in code
    # 快速档必须走开环，不能残留力控推盘
    assert "G380 S2 Y260" not in code


def test_validate_rejects_shallow_eject_offset() -> None:
    params = SwapParams(eject_offset=0.0)

    issues = validate_params(params)

    assert any("卸盘越位量" in issue for issue in issues)
    with pytest.raises(SwapCodeError):
        render_swap_code(params)


def test_validate_rejects_target_beyond_travel() -> None:
    issues = validate_params(SwapParams(approach_target=300.0))

    assert any("超出" in issue for issue in issues)


def test_validate_rejects_reversed_z_sign() -> None:
    """Z 符号写反会让机械动作反向，必须拦截。"""
    issues = validate_params(SwapParams(z_lift_before_eject=55.0))

    assert any("必须为负" in issue for issue in issues)


def test_validate_rejects_y_position_beyond_small_machine_travel() -> None:
    """A1 mini（行程 180）不能沿用 A1 的 235 等绝对坐标。"""
    params = SwapParams(y_limit=180.0, approach_target=180.0)

    issues = validate_params(params)

    assert any("超出行程上限" in issue for issue in issues)


def test_validate_rejects_unsorted_shake_offsets() -> None:
    params = SwapParams(shake_offsets=(3.5, 1.0), retract_feedrates=(20000, 20000))

    issues = validate_params(params)

    assert any("递增" in issue for issue in issues)


def test_validate_rejects_injected_force_level() -> None:
    issues = validate_params(SwapParams(force_level_push="S2\nM112"))

    assert any("力控档位" in issue for issue in issues)


def test_validate_rejects_mismatched_shake_lengths() -> None:
    params = SwapParams(shake_offsets=(1.0, 2.0), retract_feedrates=(20000,))

    issues = validate_params(params)

    assert any("数量不一致" in issue for issue in issues)


def test_duration_estimation_matches_expected_magnitude() -> None:
    """除「快慢关系」外还断言绝对量级，防止相对模式估算偏差悄悄逃逸。"""
    conservative = estimate_duration_s(CONSERVATIVE)
    fast = estimate_duration_s(FAST)

    assert 100 <= conservative <= 135
    assert fast < conservative


def test_presets_are_addressable() -> None:
    assert get_preset(CONSERVATIVE.preset_id) is CONSERVATIVE
    assert len(list_presets()) == 3

    with pytest.raises(SwapCodeError):
        get_preset("not-exist")


def test_balanced_preset_keeps_force_mode_but_shortens_dwell() -> None:
    assert BALANCED.approach_mode is ApproachMode.FORCE
    assert BALANCED.dwell_after_z_ms < CONSERVATIVE.dwell_after_z_ms
