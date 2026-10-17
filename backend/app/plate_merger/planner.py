"""自动分盘排产。

目标：给定一批待打印的件，自动决定「分几盘、每盘放什么、什么顺序」。

约束与优先级（技术方案 §17 M5）：

1. **同色同盘优先** —— 减少 AMS 换料次数，这是耗时与磨损的主要来源；
2. **单盘时长上限** —— 过长的盘一旦失败损失更大；
3. **盘架容量上限** —— 超出时按批切分并告警。

算法：按耗材分组 → 组内按单件时长降序做首次适应递减（FFD）装箱 →
展平为打印顺序。FFD 的近似比是 11/9·OPT+1，对本场景足够。
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

from .models import MergeWarning

#: 耗材标识（预设 ID, 类型, 颜色）
FilamentKey = tuple[str, str, str]


@dataclass(frozen=True)
class PlateJob:
    """一个待排产的打印件。"""

    name: str
    minutes: int
    filament: FilamentKey = ("", "", "")


@dataclass(frozen=True)
class PlannedPlate:
    """排产结果中的一盘。"""

    index: int
    jobs: tuple[PlateJob, ...] = ()
    filament: FilamentKey | None = None

    @property
    def minutes(self) -> int:
        """该盘预计耗时（分钟）。"""
        return sum(job.minutes for job in self.jobs)

    @property
    def count(self) -> int:
        """该盘件数。"""
        return len(self.jobs)


@dataclass(frozen=True)
class PlanResult:
    """排产结果。"""

    plates: tuple[PlannedPlate, ...] = ()
    warnings: tuple[MergeWarning, ...] = ()

    @property
    def total_minutes(self) -> int:
        """总耗时（分钟）。"""
        return sum(plate.minutes for plate in self.plates)


def plan(
    jobs: Sequence[PlateJob],
    *,
    max_minutes: int | None = None,
    max_plates: int = 9,
) -> PlanResult:
    """执行排产。

    :param jobs: 待打印件列表。
    :param max_minutes: 单盘时长上限（分钟）；``None`` 表示不限制。
    :param max_plates: 盘架容量上限。
    :raises ValueError: 存在非正时长的件。
    """
    for job in jobs:
        if job.minutes <= 0:
            raise ValueError(f"件时长必须为正数：{job.name}={job.minutes}")

    if not jobs:
        return PlanResult()

    # 1. 按耗材分组，保证同色同盘
    groups: dict[FilamentKey, list[PlateJob]] = defaultdict(list)
    for job in jobs:
        groups[job.filament].append(job)

    plates: list[PlannedPlate] = []
    for filament, group_jobs in groups.items():
        # 2. 组内降序，FFD 装箱
        ordered = sorted(group_jobs, key=lambda item: item.minutes, reverse=True)
        bins: list[list[PlateJob]] = []
        loads: list[int] = []

        for job in ordered:
            placed = False
            for index, load in enumerate(loads):
                if max_minutes is None or load + job.minutes <= max_minutes:
                    bins[index].append(job)
                    loads[index] += job.minutes
                    placed = True
                    break
            if not placed:
                bins.append([job])
                loads.append(job.minutes)

        for index, bin_jobs in enumerate(bins):
            plates.append(
                PlannedPlate(
                    index=len(plates) + 1,
                    jobs=tuple(bin_jobs),
                    filament=filament if any(filament) else None,
                )
            )

    warnings: list[MergeWarning] = []
    if len(plates) > max_plates:
        warnings.append(
            MergeWarning(
                code="exceeds_rack_capacity",
                message=f"需要 {len(plates)} 盘，超过盘架容量 {max_plates}，请分批执行",
            )
        )

    return PlanResult(plates=tuple(plates), warnings=tuple(warnings))
