"""测试用最小 3MF 构造工具（非测试文件，不会被 pytest 收集）。"""

from __future__ import annotations

import json
from pathlib import Path

from app.plate_merger.io3mf import CONTENT_TYPES, write_3mf

CONTENT_TYPES_XML = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'
)

END_SEQUENCE = (
    "M621 S255\n"
    "M104 S0 ; turn off hotend\n"
    "M400\n"
    "G1 Z50 F600\n"
    ";=====printer finish  sound=========\n"
    "M1006 W\n"
    "M18 X Y Z\n"
    "M73 P100 R0\n"
)


def make_gcode(plate_index: int = 1, *, slot: int = 0) -> str:
    """构造一份结构完整、可被解析的最小切片 G-code。"""
    return (
        "; HEADER_BLOCK_START\n; layer_height: 0.2\n; HEADER_BLOCK_END\n"
        "; CONFIG_BLOCK_START\n;===== A1 20251031\n; CONFIG_BLOCK_END\n"
        "; EXECUTABLE_BLOCK_START\n"
        f"G28\nG1 X{plate_index} Y{plate_index} F3000\nM620 S{slot}A\nT1000\nM621 S{slot}A\n"
        f"{END_SEQUENCE}"
        "; EXECUTABLE_BLOCK_END\n"
    )


def make_3mf(path: str | Path, colors: list[str], *, client_version: str = "02.05.03.61") -> Path:
    """生成一个多盘 3MF（每盘单耗材，局部槽位均为 0）。"""
    slice_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<config>",
        f'<header><header_item key="X-BBL-Client-Version" value="{client_version}"/></header>',
    ]
    for index, color in enumerate(colors, start=1):
        slice_lines.append(
            f'<plate><metadata key="index" value="{index}"/>'
            '<metadata key="prediction" value="100"/>'
            '<metadata key="weight" value="10"/>'
            f'<filament id="1" tray_info_idx="P25570cf" type="PETG" color="{color}" used_m="1" used_g="5"/>'
            "</plate>"
        )
    slice_lines.append("</config>")

    model_lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<config>"]
    for index in range(1, len(colors) + 1):
        model_lines.append(
            f'<plate><metadata key="plater_id" value="{index}"/>'
            f'<metadata key="gcode_file" value="Metadata/plate_{index}.gcode"/></plate>'
        )
    model_lines.append("</config>")

    members: dict[str, bytes] = {
        CONTENT_TYPES: CONTENT_TYPES_XML,
        "Metadata/slice_info.config": "\n".join(slice_lines).encode(),
        "Metadata/model_settings.config": "\n".join(model_lines).encode(),
        "Metadata/filament_sequence.json": json.dumps({"plate_1": {"sequence": [1]}}).encode(),
        "Metadata/plate_1.json": json.dumps(
            {"filament_colors": ["#FFFFFF"], "filament_ids": ["GFL99"], "bed_type": "textured_plate"}
        ).encode(),
        "Metadata/project_settings.config": json.dumps(
            {
                "filament_colour": ["#FFFFFF"],
                "filament_type": ["PETG"],
                "filament_ids": ["GFL99"],
                "filament_settings_id": ["Generic PETG @Bambu Lab A1 0.4 nozzle"],
                "filament_maps": "1 1 1 1 1",
            }
        ).encode(),
    }
    for index in range(1, len(colors) + 1):
        members[f"Metadata/plate_{index}.gcode"] = make_gcode(index).encode()
        members[f"Metadata/plate_{index}.png"] = b"\x89PNG\r\n"

    return write_3mf(path, members)
