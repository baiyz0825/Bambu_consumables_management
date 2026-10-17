"""合盘后的 3MF 元数据重写。

实测结构（02.05 / 02.08 一致）：

- ``Metadata/model_settings.config``：**每个 plate 一个 ``<plate>``**，
  其中 ``gcode_file`` 才是指向实际 G-code 的入口 —— 这是合盘后最关键的改动点；
- ``Metadata/slice_info.config``：每盘的 ``prediction`` / ``weight`` 与 ``<filament>`` 清单；
- ``Metadata/filament_sequence.json``：每盘使用的耗材编号（1-based）；
- ``Metadata/plate_N.json``：颜色、床型等展示信息。

合并后必须让打印机「只看到一个盘」，因此：

1. ``model_settings`` 只保留第一个 ``<plate>``，``gcode_file`` 指向合并后的 G-code；
2. ``slice_info`` 只保留一个 ``<plate>``，时长与重量取合计，耗材换为全局清单；
3. ``filament_sequence`` 只保留 ``plate_1``；
4. 其余 plate 相关文件在打包时删除。

XML 重写使用标准库 ElementTree；写出时补回 XML 声明，保持与 Bambu 原生文件一致。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from xml.etree import ElementTree

from .errors import MetadataError
from .filament import GlobalFilament
from .models import FilamentRef

#: 合并后固定使用的 G-code 成员名
MERGED_GCODE_MEMBER = "Metadata/plate_1.gcode"

#: 指向「第 N 盘」的资源引用，需要统一改成第 1 盘
_PLATE_ASSET_PATTERN = re.compile(r"((?:plate_no_light_|plate_small_|plate_|top_|pick_))(\d+)(\.[A-Za-z0-9]+)$")

#: 与盘号绑定的资源文件名（不含目录），用于合盘后清理第 2 盘及以后的资源。
#: 单一来源：流水线清理与元数据重写必须用同一套命名规则，否则会漏删或误改。
MULTI_PLATE_ASSET_PATTERN = re.compile(
    r"^(?:plate_(\d+)\.(?:gcode|gcode\.md5|png|json)|plate_no_light_(\d+)\.png|top_(\d+)\.png|pick_(\d+)\.png)$",
    re.IGNORECASE,
)

_XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>'


def _parse_xml(text: str, *, source: str) -> ElementTree.Element:
    """解析 XML，失败时抛工程内异常。"""
    try:
        return ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise MetadataError(f"{source} 不是合法 XML", detail={"source": source, "reason": str(exc)}) from exc


def _serialize_xml(root: ElementTree.Element) -> str:
    """序列化并补回 XML 声明。"""
    body = ElementTree.tostring(root, encoding="unicode")
    return f"{_XML_DECLARATION}\n{body}"


def _single_plate(root: ElementTree.Element, *, source: str) -> ElementTree.Element:
    """取出唯一要保留的 ``<plate>``，并移除其余条目。"""
    plates = root.findall("plate")
    if not plates:
        raise MetadataError(f"{source} 中没有 <plate> 节点", detail={"source": source})
    for extra in plates[1:]:
        root.remove(extra)
    return plates[0]


def _rewrite_asset_reference(value: str) -> str:
    """把指向第 N 盘的资源引用改到第 1 盘。"""
    return _PLATE_ASSET_PATTERN.sub(lambda match: f"{match.group(1)}1{match.group(3)}", value)


def rewrite_model_settings(text: str, *, gcode_member: str = MERGED_GCODE_MEMBER) -> str:
    """收敛 ``model_settings.config`` 为单盘，并把 ``gcode_file`` 指向合并产物。

    :raises MetadataError: XML 非法或缺少 ``<plate>``。
    """
    root = _parse_xml(text, source="model_settings.config")
    plate = _single_plate(root, source="model_settings.config")

    for metadata in plate.findall("metadata"):
        key = metadata.get("key")
        if key == "plater_id":
            metadata.set("value", "1")
        elif key == "gcode_file":
            metadata.set("value", gcode_member)
        elif key in {
            "thumbnail_file",
            "thumbnail_no_light_file",
            "top_file",
            "pick_file",
            "pattern_bbox_file",
        }:
            current = metadata.get("value") or ""
            metadata.set("value", _rewrite_asset_reference(current))

    # 子元素顺序对 Bambu 不重要（按标签名查找），但保持 plate 在前更接近原生文件
    return _serialize_xml(root)


def rewrite_slice_info(
    text: str,
    *,
    prediction_s: int | None,
    weight_g: float | None,
    filaments: Sequence[GlobalFilament],
) -> str:
    """合并 ``slice_info.config``：单盘 + 合计时长重量 + 全局耗材清单。

    注意 ``<filament id>`` 必须使用**全局槽位**（``GlobalFilament.slot + 1``），
    不能用原始 ``FilamentRef.slot`` —— 后者是盘内局部编号，多盘单色场景下
    会产生多条重复 ``id="1"``，与 G-code 的 ``M620 S0/S1/S2`` 完全对不上。

    :raises MetadataError: XML 非法或缺少 ``<plate>``。
    """
    root = _parse_xml(text, source="slice_info.config")
    plate = _single_plate(root, source="slice_info.config")

    for metadata in plate.findall("metadata"):
        key = metadata.get("key")
        if key == "index":
            metadata.set("value", "1")
        elif key == "prediction" and prediction_s is not None:
            metadata.set("value", str(int(prediction_s)))
        elif key == "weight" and weight_g is not None:
            metadata.set("value", f"{weight_g:g}")

    for existing in plate.findall("filament"):
        plate.remove(existing)

    for item in filaments:
        element = ElementTree.SubElement(plate, "filament")
        element.set("id", str(item.slot + 1))
        if item.ref.tray_info_idx:
            element.set("tray_info_idx", item.ref.tray_info_idx)
        if item.ref.type:
            element.set("type", item.ref.type)
        if item.ref.color:
            element.set("color", item.ref.color)
        if item.total_used_m:
            element.set("used_m", f"{item.total_used_m:.2f}")
        if item.total_used_g:
            element.set("used_g", f"{item.total_used_g:.2f}")

    return _serialize_xml(root)


def rewrite_filament_sequence(text: str, *, slots: int) -> str:
    """只保留 ``plate_1``，并按全局槽位数生成顺序。

    :param slots: 全局占用槽位数；生成 ``1..slots`` 的 1-based 序列。
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MetadataError("filament_sequence.json 不是合法 JSON", detail={"reason": str(exc)}) from exc

    if not isinstance(data, dict):
        raise MetadataError("filament_sequence.json 根节点不是对象")

    merged = {"plate_1": {"sequence": list(range(1, slots + 1))}}
    # 保留未知顶层键，避免新版字段被丢弃
    for key, value in data.items():
        if not key.startswith("plate_"):
            merged[key] = value
    return json.dumps(merged, ensure_ascii=False, separators=(",", ":"))


def rewrite_plate_json(text: str, *, filaments: Sequence[FilamentRef]) -> str:
    """更新 ``plate_1.json`` 中的颜色与耗材预设 ID。

    未知键原样保留（新版本会新增字段）。
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MetadataError("plate_1.json 不是合法 JSON", detail={"reason": str(exc)}) from exc

    if not isinstance(data, dict):
        raise MetadataError("plate_1.json 根节点不是对象")

    if "filament_colors" in data:
        data["filament_colors"] = [ref.color for ref in filaments]
    if "filament_ids" in data:
        data["filament_ids"] = [ref.tray_info_idx for ref in filaments]
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


#: 需要按耗材逐项重写的数组键
_COLOR_KEYS = frozenset({"filament_colour", "default_filament_colour"})
_TYPE_KEYS = frozenset({"filament_type"})
_ID_KEYS = frozenset({"filament_ids"})


def rewrite_project_settings(text: str, *, filaments: Sequence[GlobalFilament]) -> str:
    """按全局槽位扩展/收缩 ``project_settings.config`` 中的耗材数组。

    为什么必须做：基底文件来自第一个盘，其 ``filament_colour`` 等数组长度只对应**那一盘**的耗材数。
    合盘后 G-code 可能用到 3 个槽位，而 Studio 只看到 1 个 —— 用户手动映射 AMS 时会改错料。

    处理规则：

    - 颜色 / 类型 / 预设 ID 数组按全局耗材逐项重写；
    - 其余 ``filament_*`` / ``nozzle_*`` 数组按全局数量循环补齐（保持首项语义）；
    - 非数组值（如 ``filament_maps`` 是空格分隔字符串）原样保留。
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MetadataError("project_settings.config 不是合法 JSON", detail={"reason": str(exc)}) from exc
    if not isinstance(data, dict):
        raise MetadataError("project_settings.config 根节点不是对象")

    target_len = len(filaments)
    if target_len == 0:
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    for key, value in list(data.items()):
        if not isinstance(value, list) or not value:
            continue

        if key in _COLOR_KEYS:
            data[key] = [item.ref.color for item in filaments]
        elif key in _TYPE_KEYS:
            data[key] = [item.ref.type for item in filaments]
        elif key in _ID_KEYS:
            data[key] = [item.ref.tray_info_idx for item in filaments]
        elif key.startswith(("filament_", "nozzle_")):
            data[key] = [value[index % len(value)] for index in range(target_len)]

    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def strip_extra_plate_assets(members: dict[str, bytes], *, keep: int = 1) -> None:
    """删除第 ``keep`` 盘以外的所有盘资源（就地修改）。

    合盘后只剩一个盘，其余 ``plate_N.*`` / ``top_N.*`` / ``pick_N.*`` 必须清理，
    否则包内会残留指向已不存在 G-code 的引用。
    """
    for name in list(members):
        basename = name.rsplit("/", 1)[-1]
        match = MULTI_PLATE_ASSET_PATTERN.match(basename)
        if not match:
            continue
        number = next((group for group in match.groups() if group), None)
        if number is not None and int(number) != keep:
            del members[name]


def resolve_auxiliary_targets(project_settings: Mapping[str, object]) -> Mapping[str, object]:
    """占位：保留扩展点。

    目前耗材数组重写由 :func:`rewrite_project_settings` 负责；
    此函数供未来处理其它辅助配置（如缩略图引用）时集中扩展。
    """
    return project_settings
