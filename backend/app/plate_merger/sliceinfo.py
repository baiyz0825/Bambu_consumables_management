"""3MF 元数据解析：``slice_info.config`` / ``plate_N.json`` / ``filament_sequence.json``。

三条关键事实（技术方案 §4.2 实测）：

1. 耗材编号是**每盘独立**的：同一个 ``M620 S0A`` 在不同盘可能对应不同颜色；
2. 槽位编号在两处基准不同 —— XML 的 ``<filament id>`` 是 **1-based**，
   G-code 的 ``M620 S{n}A`` 是 **0-based**，本模块统一转换为 0-based ``slot``；
3. 新版本只增字段不减字段，因此解析必须**按 key 取值**并**透传未知字段**，
   不能按行号或元素顺序。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from xml.etree import ElementTree

from .errors import MetadataError
from .models import FilamentRef
from .utils import normalize_color, to_bool, to_float, to_int

#: ``<filament>`` 上本模块显式消费的属性；其余属性原样放入 :attr:`FilamentRef.extra`，
#: 以兼容切片器后续新增字段（如 02.08 的 ``total_load_time``）。
_FILAMENT_KNOWN_ATTRS = frozenset({"id", "tray_info_idx", "type", "color", "used_g", "used_m"})


@dataclass(frozen=True)
class SliceHeader:
    """``slice_info.config`` 的 header 段，含切片器客户端版本。"""

    values: Mapping[str, str] = field(default_factory=dict, compare=False, hash=False)

    @property
    def client_version(self) -> str | None:
        """切片器客户端版本（如 ``02.08.02.61``），缺失返回 ``None``。"""
        return self.values.get("X-BBL-Client-Version") or None

    @property
    def client_type(self) -> str | None:
        """客户端类型（通常为 ``slicer``）。"""
        return self.values.get("X-BBL-Client-Type") or None


@dataclass(frozen=True)
class SlicePlate:
    """``slice_info.config`` 中单个 ``<plate>`` 的只读内容。

    与 :class:`plate_merger.models.PlateInfo` 的区别：本类型不含 ``gcode_member``，
    因为元数据解析时还不需要知道 G-code 成员名；组装由流水线完成。
    """

    index: int
    prediction_s: int | None = None
    weight_g: float | None = None
    filaments: tuple[FilamentRef, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict, compare=False, hash=False)


@dataclass(frozen=True)
class SliceInfo:
    """整份 ``slice_info.config`` 的解析结果。"""

    header: SliceHeader
    plates: tuple[SlicePlate, ...]

    def plate(self, index: int) -> SlicePlate | None:
        """按盘号取单个盘，不存在返回 ``None``。"""
        for item in self.plates:
            if item.index == index:
                return item
        return None


@dataclass(frozen=True)
class PlateJson:
    """``plate_N.json`` 中与合盘相关的字段（其余原样保留在 ``raw``）。"""

    filament_colors: tuple[str, ...] = ()
    filament_ids: tuple[str, ...] = ()
    bed_type: str | None = None
    first_extruder: int | None = None
    is_seq_print: bool = False
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, hash=False)


def parse_slice_info(text: str) -> SliceInfo:
    """解析 ``Metadata/slice_info.config``。

    :raises MetadataError: XML 非法或缺少 ``<config>`` 根节点。
    """
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise MetadataError("slice_info.config 不是合法 XML", detail={"reason": str(exc)}) from exc

    if root.tag != "config":
        raise MetadataError("slice_info.config 根节点不是 config", detail={"tag": root.tag})

    header: dict[str, str] = {}
    header_element = root.find("header")
    if header_element is not None:
        for item in header_element.findall("header_item"):
            key = item.get("key")
            if key:
                header[key] = item.get("value") or ""

    plates: list[SlicePlate] = []
    for position, plate_element in enumerate(root.findall("plate"), start=1):
        metadata: dict[str, str] = {}
        for item in plate_element.findall("metadata"):
            key = item.get("key")
            if key:
                metadata[key] = item.get("value") or ""

        filaments: list[FilamentRef] = []
        for filament_position, filament in enumerate(plate_element.findall("filament")):
            # XML 中 id 从 1 开始，G-code 中槽位从 0 开始；缺失 id 属格式异常，不能猜
            raw_id = to_int(filament.get("id"))
            if raw_id is None or raw_id < 1:
                raise MetadataError(
                    "filament 缺少合法 id",
                    detail={
                        "plate": position,
                        "position": filament_position,
                        "id": filament.get("id"),
                    },
                )
            attributes = dict(filament.attrib)
            extra = {key: value for key, value in attributes.items() if key not in _FILAMENT_KNOWN_ATTRS}
            filaments.append(
                FilamentRef(
                    slot=raw_id - 1,
                    tray_info_idx=attributes.get("tray_info_idx") or "",
                    type=attributes.get("type") or "",
                    color=normalize_color(attributes.get("color")),
                    used_g=to_float(attributes.get("used_g")),
                    used_m=to_float(attributes.get("used_m")),
                    extra=extra,
                )
            )

        raw_index = to_int(metadata.get("index"))
        plates.append(
            SlicePlate(
                # 注意不能用 `or`：盘号 0 是合法整数，会被误判为空
                index=raw_index if raw_index is not None else position,
                prediction_s=to_int(metadata.get("prediction")),
                weight_g=to_float(metadata.get("weight")),
                filaments=tuple(filaments),
                metadata=metadata,
            )
        )

    plates.sort(key=lambda item: item.index)
    return SliceInfo(header=SliceHeader(values=header), plates=tuple(plates))


def parse_plate_json(text: str) -> PlateJson:
    """解析 ``Metadata/plate_N.json``。

    :raises MetadataError: JSON 非法或根节点不是对象。
    """
    data = _load_json_object(text, source="plate_N.json")
    colors = _require_list(data.get("filament_colors"), field="filament_colors")
    ids = _require_list(data.get("filament_ids"), field="filament_ids")
    return PlateJson(
        filament_colors=tuple(normalize_color(item) for item in colors if isinstance(item, str)),
        filament_ids=tuple(item for item in ids if isinstance(item, str)),
        bed_type=data.get("bed_type") if isinstance(data.get("bed_type"), str) else None,
        first_extruder=to_int(data.get("first_extruder")),
        is_seq_print=to_bool(data.get("is_seq_print")),
        raw=data,
    )


def _require_list(value: Any, *, field: str) -> list[Any]:
    """要求字段是数组（缺省视为空数组）。

    若某版本把它写成字符串，按字符迭代会产出垃圾数据，因此这里显式报错。
    """
    if value is None:
        return []
    if not isinstance(value, list):
        raise MetadataError(f"{field} 必须是数组", detail={"field": field, "type": type(value).__name__})
    return value


def parse_filament_sequence(text: str) -> dict[int, tuple[int, ...]]:
    """解析 ``Metadata/filament_sequence.json``。

    结构形如 ``{"plate_1": {"sequence": [1]}, "plate_2": {"sequence": [3]}}``。
    值为 **1-based** 耗材编号，与 ``slice_info`` 的 ``<filament id>`` 同基准。

    :return: ``{盘号: 耗材编号元组}``
    :raises MetadataError: JSON 非法。
    """
    data = _load_json_object(text, source="filament_sequence.json")
    result: dict[int, tuple[int, ...]] = {}
    for key, value in data.items():
        if not key.startswith("plate_"):
            continue
        plate_index = to_int(key.removeprefix("plate_"))
        if plate_index is None or not isinstance(value, dict):
            continue
        sequence = value.get("sequence")
        if isinstance(sequence, list):
            result[plate_index] = tuple(item for item in (to_int(entry) for entry in sequence) if item is not None)
    return result


def parse_project_settings(text: str) -> Mapping[str, Any]:
    """解析 ``Metadata/project_settings.config``（JSON）。

    不做白名单过滤 —— 新版本会增加键（实测 02.05 有 558 个、02.08 有 581 个），
    未知键必须原样透传。

    :raises MetadataError: JSON 非法。
    """
    return _load_json_object(text, source="project_settings.config")


def _load_json_object(text: str, *, source: str) -> dict[str, Any]:
    """解析 JSON 并确保根节点是对象。"""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MetadataError(f"{source} 不是合法 JSON", detail={"source": source, "reason": str(exc)}) from exc
    if not isinstance(data, dict):
        raise MetadataError(f"{source} 根节点不是对象", detail={"source": source, "type": type(data).__name__})
    return data
