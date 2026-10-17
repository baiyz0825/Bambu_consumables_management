"""耗材全局重映射测试：覆盖跨盘去重、槽位重写与异常路径。"""

from __future__ import annotations

import pytest

from plate_merger.errors import ValidationError
from plate_merger.filament import build_plan, remap_gcode
from plate_merger.models import FilamentRef, PlateInfo

YELLOW = "#F6DA5A"
WHITE = "#FFFFFF"
BLACK = "#161616"


def _ref(slot: int, color: str, *, type_: str = "PETG", tray: str = "P25570cf", used: float | None = None) -> FilamentRef:
    return FilamentRef(slot=slot, tray_info_idx=tray, type=type_, color=color, used_g=used)


def _plate(index: int, *refs: FilamentRef) -> PlateInfo:
    return PlateInfo(index=index, gcode_member=f"Metadata/plate_{index}.gcode", filaments=tuple(refs))


def test_same_filament_across_plates_shares_one_global_slot() -> None:
    plan = build_plan([_plate(1, _ref(0, YELLOW)), _plate(2, _ref(0, YELLOW))])

    assert plan.slot_count == 1
    assert plan.mapping_for(1) == {0: 0}
    assert plan.mapping_for(2) == {0: 0}


def test_different_colors_get_distinct_global_slots() -> None:
    plan = build_plan([_plate(1, _ref(0, YELLOW)), _plate(2, _ref(0, WHITE))])

    assert plan.slot_count == 2
    assert plan.mapping_for(1) == {0: 0}
    assert plan.mapping_for(2) == {0: 1}


def test_same_local_slot_maps_to_different_global_slots() -> None:
    """核心场景：同一个 S0 在不同盘是不同颜色，必须各自映射。"""
    plan = build_plan(
        [
            _plate(1, _ref(0, YELLOW)),
            _plate(2, _ref(0, WHITE)),
            _plate(3, _ref(0, BLACK)),
        ]
    )

    assert plan.mapping_for(1)[0] != plan.mapping_for(2)[0]
    assert plan.mapping_for(2)[0] != plan.mapping_for(3)[0]
    assert [item.color for item in plan.filaments] == [YELLOW, WHITE, BLACK]


def test_total_usage_is_accumulated_per_global_slot() -> None:
    plan = build_plan([_plate(1, _ref(0, YELLOW, used=10.5)), _plate(2, _ref(0, YELLOW, used=4.5))])

    assert plan.filaments[0].total_used_g == pytest.approx(15.0)


def test_plate_indexes_are_recorded() -> None:
    plan = build_plan([_plate(1, _ref(0, YELLOW)), _plate(2, _ref(0, YELLOW)), _plate(3, _ref(0, WHITE))])

    assert plan.filaments[0].plate_indexes == (1, 2)
    assert plan.filaments[1].plate_indexes == (3,)


def test_warns_when_slots_exceed_ams_capacity() -> None:
    plan = build_plan([_plate(index, _ref(0, color)) for index, color in enumerate(
        ["#111111", "#222222", "#333333", "#444444", "#555555"], start=1
    )])

    assert plan.slot_count == 5
    assert any(warning.code == "too_many_slots" for warning in plan.warnings)


def test_duplicate_local_slot_in_same_plate_is_rejected() -> None:
    with pytest.raises(ValidationError):
        build_plan([_plate(1, _ref(0, YELLOW), _ref(0, WHITE))])


def test_unknown_plate_mapping_raises() -> None:
    plan = build_plan([_plate(1, _ref(0, YELLOW))])

    with pytest.raises(ValidationError):
        plan.mapping_for(99)


def test_remap_rewrites_m620_and_m621() -> None:
    code = "M620 S0A\nT1000\nM621 S0A\n"

    assert remap_gcode(code, {0: 2}) == "M620 S2A\nT1000\nM621 S2A\n"


def test_remap_keeps_reserved_slot_255() -> None:
    code = "M620 S255A\nM621 S255A\n"

    assert remap_gcode(code, {0: 2}) == code


def test_remap_keeps_tool_commands_untouched() -> None:
    """T1000 是内置工具号，不是槽位，不能参与重写。"""
    assert remap_gcode("T1000\nT0\n", {0: 3}) == "T1000\nT0\n"


def test_remap_raises_on_unmapped_slot() -> None:
    with pytest.raises(ValidationError):
        remap_gcode("M620 S1A\n", {0: 0})


def test_remap_handles_multiple_slots() -> None:
    code = "M620 S0A\nM621 S0A\nM620 S1A\nM621 S1A\n"

    assert remap_gcode(code, {0: 1, 1: 0}) == "M620 S1A\nM621 S1A\nM620 S0A\nM621 S0A\n"
