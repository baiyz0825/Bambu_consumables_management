"""排产逻辑测试：同色聚簇、时长上限与容量告警。"""

from __future__ import annotations

import pytest

from plate_merger.planner import PlateJob, plan

YELLOW = ("P25570cf", "PETG", "#F6DA5A")
WHITE = ("P25570cf", "PETG", "#FFFFFF")


def test_empty_jobs_returns_empty_plan() -> None:
    result = plan([])

    assert result.plates == ()
    assert result.total_minutes == 0


def test_same_filament_prefers_single_plate() -> None:
    jobs = [PlateJob("a", 30, YELLOW), PlateJob("b", 30, YELLOW)]

    result = plan(jobs, max_minutes=120)

    assert len(result.plates) == 1
    assert result.plates[0].minutes == 60


def test_different_filaments_separate_plates() -> None:
    jobs = [PlateJob("a", 30, YELLOW), PlateJob("b", 30, WHITE)]

    result = plan(jobs)

    assert len(result.plates) == 2
    assert {plate.filament for plate in result.plates} == {YELLOW, WHITE}


def test_max_minutes_splits_into_multiple_plates() -> None:
    jobs = [PlateJob(str(index), 40, YELLOW) for index in range(3)]

    result = plan(jobs, max_minutes=80)

    assert len(result.plates) == 2
    assert all(plate.minutes <= 80 for plate in result.plates)


def test_descending_first_fit_is_applied() -> None:
    jobs = [PlateJob("small", 10, YELLOW), PlateJob("big", 70, YELLOW)]

    result = plan(jobs, max_minutes=80)

    assert len(result.plates) == 1
    # 大件先放，小件填缝
    assert [job.name for job in result.plates[0].jobs] == ["big", "small"]


def test_exceeding_rack_capacity_warns() -> None:
    jobs = [PlateJob(str(index), 30, (f"id{index}", "PLA", f"#00000{index}")) for index in range(4)]

    result = plan(jobs, max_plates=2)

    assert len(result.plates) == 4
    assert any(warning.code == "exceeds_rack_capacity" for warning in result.warnings)


def test_non_positive_minutes_rejected() -> None:
    with pytest.raises(ValueError):
        plan([PlateJob("bad", 0, YELLOW)])


def test_plate_indexes_are_sequential() -> None:
    jobs = [PlateJob("a", 10, YELLOW), PlateJob("b", 10, WHITE), PlateJob("c", 10, ("x", "PLA", "#111111"))]

    result = plan(jobs)

    assert [plate.index for plate in result.plates] == [1, 2, 3]
