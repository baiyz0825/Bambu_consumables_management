"""切片产物版本指纹探测。

用途（技术方案 §17 M1）：Bambu Studio 的新版本只增字段、不改结构，
但模板 G-code（machine start / change filament）会变。把每次新版本切片的关键特征存成指纹，
就能在导入时自动判断「已知版本直接放行 / 未知版本提示差异」。

设计原则：指纹只记录**结构特征**，不记录业务数据，
因此可以安全地跨机型、跨项目比较。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .gcode import GcodeBlocks, extract_header_block
from .io3mf import ThreeMfPackage
from .sliceinfo import parse_plate_json, parse_project_settings, parse_slice_info

#: 模板版本串，如 ``;===== A1 20251031``
_TEMPLATE_A1 = re.compile(r"^;\s*=====\s*A1\s+(\d{6,8})", re.MULTILINE)
#: 机器模板日期，如 ``date: 20250821``
_TEMPLATE_DATE = re.compile(r"date:\s*(\d{6,8})")
#: HEADER 中的键行，形如 ``; key: value``
_HEADER_KEY = re.compile(r"^;\s*([A-Za-z_][\w ]*?)\s*:", re.MULTILINE)


@dataclass(frozen=True)
class Fingerprint:
    """一份切片产物的结构指纹。"""

    client_version: str | None
    plate_count: int
    has_executable_block: bool
    slice_info_keys: tuple[str, ...]
    filament_attrs: tuple[str, ...]
    project_settings_key_count: int
    template_versions: tuple[str, ...]
    header_keys: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        """转成可 JSON 序列化的字典。"""
        data = asdict(self)
        for key, value in data.items():
            if isinstance(value, tuple):
                data[key] = list(value)
        return data


def probe(path: str | Path) -> Fingerprint:
    """探测一个 3MF 的结构指纹。

    :raises PlateMergerError: 不是合法 3MF 或缺少必要成员。
    """
    with ThreeMfPackage.open(path) as package:
        gcodes = package.plate_gcodes()
        if not gcodes:
            from .errors import UnsupportedFormatError

            raise UnsupportedFormatError("不是已切片 3MF", detail={"path": str(path)})

        slice_info = parse_slice_info(package.read_text("Metadata/slice_info.config"))
        gcode_text = package.read_text(gcodes[0][1])

        project_keys = 0
        if package.has("Metadata/project_settings.config"):
            project_keys = len(parse_project_settings(package.read_text("Metadata/project_settings.config")))

        filament_attrs: set[str] = set()
        plate_json_members = [name for name in package.names if re.search(r"Metadata/plate_\d+\.json$", name, re.I)]
        if plate_json_members:
            raw = package.read_text(plate_json_members[0])
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {}
            if isinstance(payload, dict):
                filament_attrs.update(str(key) for key in payload)

        blocks_ok = True
        try:
            GcodeBlocks.parse(gcode_text)
        except Exception:  # noqa: BLE001 - 指纹探测不应因结构异常而中断
            blocks_ok = False

        header = extract_header_block(gcode_text) or ""
        header_keys = tuple(dict.fromkeys(_HEADER_KEY.findall(header)))

        templates = tuple(
            sorted({*_TEMPLATE_A1.findall(gcode_text), *_TEMPLATE_DATE.findall(gcode_text)})
        )

        return Fingerprint(
            client_version=slice_info.header.client_version,
            plate_count=len(gcodes),
            has_executable_block=blocks_ok,
            slice_info_keys=tuple(sorted({key for plate in slice_info.plates for key in plate.metadata})),
            filament_attrs=tuple(sorted(filament_attrs)),
            project_settings_key_count=project_keys,
            template_versions=templates,
            header_keys=header_keys,
        )


def diff(base: Fingerprint, current: Fingerprint) -> tuple[str, ...]:
    """比较两份指纹，返回人类可读的差异描述。"""
    changes: list[str] = []

    if base.client_version != current.client_version:
        changes.append(f"客户端版本 {base.client_version} -> {current.client_version}")
    if base.plate_count != current.plate_count:
        changes.append(f"盘数 {base.plate_count} -> {current.plate_count}")
    if base.has_executable_block != current.has_executable_block:
        changes.append(f"EXECUTABLE 块存在性 {base.has_executable_block} -> {current.has_executable_block}")
    if base.project_settings_key_count != current.project_settings_key_count:
        changes.append(
            f"project_settings 键数 {base.project_settings_key_count} -> {current.project_settings_key_count}"
        )

    added = sorted(set(current.slice_info_keys) - set(base.slice_info_keys))
    removed = sorted(set(base.slice_info_keys) - set(current.slice_info_keys))
    if added:
        changes.append(f"slice_info 新增键：{added}")
    if removed:
        changes.append(f"slice_info 移除键：{removed}")

    added_attr = sorted(set(current.filament_attrs) - set(base.filament_attrs))
    if added_attr:
        changes.append(f"plate json 新增键：{added_attr}")

    if base.template_versions != current.template_versions:
        changes.append(f"G-code 模板版本 {base.template_versions} -> {current.template_versions}")

    return tuple(changes)
