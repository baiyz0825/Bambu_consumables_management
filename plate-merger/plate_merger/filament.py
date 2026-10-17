"""耗材全局重映射。

背景（技术方案 §4.2 实测）：3MF 里的耗材编号是**每盘独立**的 ——
同一个 ``M620 S0A`` 在 A 盘可能对应黄色、在 B 盘可能是白色。
若直接把多盘 G-code 拼在一起，打印机换盘后会继续用旧槽位，导致用错料。

处理流程：

1. 收集所有盘的 :class:`~plate_merger.models.FilamentRef`；
2. 按 ``(tray_info_idx, type, color)`` 三元组去重，建立全局槽位表；
3. 为每盘生成 ``本地槽位 -> 全局槽位`` 映射；
4. 拼接时用该映射重写 ``M620 S{n}A`` / ``M621 S{n}A``。

设计取舍：

- **只重写换料指令，不动 ``T`` 指令**：Bambu 用 ``T1000`` 表示内置工具，它不是槽位号。
- **映射缺失即抛错**：原样输出等于用错料，属于不可接受的静默错误。
- **``255`` 保留不动**：它表示「全部/退料」，不是槽位。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .errors import ValidationError
from .models import FilamentRef, MergeWarning, PlateInfo

#: 表示退料/全部的特殊槽位号，不参与重映射
RESERVED_SLOT = 255

#: AMS Lite 的槽位上限；超过时无法自动映射
AMS_LITE_SLOTS = 4

_M620_PATTERN = re.compile(r"(M620\s+S)(\d+)(A?)")
_M621_PATTERN = re.compile(r"(M621\s+S)(\d+)(A?)")


@dataclass(frozen=True)
class GlobalFilament:
    """全局槽位：跨盘去重后的一种耗材。"""

    slot: int
    ref: FilamentRef
    plate_indexes: tuple[int, ...] = ()
    total_used_g: float = 0.0
    total_used_m: float = 0.0

    @property
    def color(self) -> str:
        """耗材颜色（``#RRGGBB``）。"""
        return self.ref.color

    @property
    def type(self) -> str:
        """耗材类型（如 ``PLA`` / ``PETG``）。"""
        return self.ref.type


@dataclass(frozen=True)
class PlateMapping:
    """单个盘的槽位映射。"""

    plate_index: int
    local_to_global: Mapping[int, int] = field(default_factory=dict)


@dataclass(frozen=True)
class FilamentPlan:
    """整体耗材方案。"""

    filaments: tuple[GlobalFilament, ...]
    mappings: tuple[PlateMapping, ...]
    warnings: tuple[MergeWarning, ...] = ()

    def mapping_for(self, plate_index: int) -> Mapping[int, int]:
        """取某盘的槽位映射。

        :raises ValidationError: 该盘未参与规划。
        """
        for item in self.mappings:
            if item.plate_index == plate_index:
                return item.local_to_global
        raise ValidationError("盘未参与耗材规划", detail={"plate_index": plate_index})

    @property
    def slot_count(self) -> int:
        """全局占用的槽位数。"""
        return len(self.filaments)


def build_plan(plates: Sequence[PlateInfo], *, ams_slots: int = AMS_LITE_SLOTS) -> FilamentPlan:
    """构建全局耗材方案。

    :param plates: 参与合并的盘（顺序即打印顺序）。
    :param ams_slots: 可用槽位数，用于超出告警。
    :raises ValidationError: 同一盘内出现重复槽位（元数据异常）。
    """
    order: list[FilamentRef] = []
    identity_to_slot: dict[tuple[str, str, str], int] = {}
    plate_of_slot: dict[int, list[int]] = {}
    usage_of_slot: dict[int, float] = {}
    length_of_slot: dict[int, float] = {}
    mappings: list[PlateMapping] = []

    for plate in plates:
        seen_local: set[int] = set()
        local_map: dict[int, int] = {}

        for ref in plate.filaments:
            if ref.slot in seen_local:
                raise ValidationError(
                    "同一盘内出现重复槽位",
                    detail={"plate_index": plate.index, "slot": ref.slot},
                )
            seen_local.add(ref.slot)

            identity = ref.identity
            global_slot = identity_to_slot.get(identity)
            if global_slot is None:
                global_slot = len(order)
                identity_to_slot[identity] = global_slot
                order.append(ref)
                plate_of_slot[global_slot] = []
                usage_of_slot[global_slot] = 0.0
                length_of_slot[global_slot] = 0.0

            local_map[ref.slot] = global_slot
            if plate.index not in plate_of_slot[global_slot]:
                plate_of_slot[global_slot].append(plate.index)
            usage_of_slot[global_slot] += ref.used_g or 0.0
            length_of_slot[global_slot] += ref.used_m or 0.0

        mappings.append(PlateMapping(plate_index=plate.index, local_to_global=local_map))

    filaments = tuple(
        GlobalFilament(
            slot=slot,
            ref=ref,
            plate_indexes=tuple(plate_of_slot.get(slot, [])),
            total_used_g=round(usage_of_slot.get(slot, 0.0), 3),
            total_used_m=round(length_of_slot.get(slot, 0.0), 3),
        )
        for slot, ref in enumerate(order)
    )

    warnings: list[MergeWarning] = []
    if len(filaments) > ams_slots:
        warnings.append(
            MergeWarning(
                code="too_many_slots",
                message=f"全局耗材占用 {len(filaments)} 个槽位，超过可用 {ams_slots} 槽，需人工换料或分批",
            )
        )

    return FilamentPlan(filaments=filaments, mappings=tuple(mappings), warnings=tuple(warnings))


def remap_gcode(text: str, mapping: Mapping[int, int]) -> str:
    """重写 G-code 中的槽位编号。

    :param text: 单盘的打印段 G-code。
    :param mapping: ``本地槽位 -> 全局槽位``。
    :raises ValidationError: 遇到未在映射中登记的槽位。
    """

    def replace(match: re.Match[str]) -> str:
        prefix, raw_slot, suffix = match.group(1), int(match.group(2)), match.group(3)
        if raw_slot == RESERVED_SLOT:
            return match.group(0)
        global_slot = mapping.get(raw_slot)
        if global_slot is None:
            raise ValidationError(
                "G-code 中的槽位未在耗材规划中登记",
                detail={"slot": raw_slot, "known": sorted(mapping)},
            )
        return f"{prefix}{global_slot}{suffix}"

    # 先 M620 再 M621：两者互不重叠，顺序不影响结果
    result = _M620_PATTERN.sub(replace, text)
    return _M621_PATTERN.sub(replace, result)
