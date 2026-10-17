"""元数据重写测试：重点是「槽位必须用全局编号」这一契约。"""

from __future__ import annotations

import json
import re

import pytest

from app.plate_merger.errors import MetadataError
from app.plate_merger.filament import GlobalFilament
from app.plate_merger.metadata import (
    rewrite_filament_sequence,
    rewrite_model_settings,
    rewrite_plate_json,
    rewrite_slice_info,
)
from app.plate_merger.models import FilamentRef

_SLICE_INFO = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <header><header_item key="X-BBL-Client-Version" value="02.05.03.61"/></header>
  <plate>
    <metadata key="index" value="1"/>
    <metadata key="prediction" value="100"/>
    <metadata key="weight" value="10"/>
    <filament id="1" tray_info_idx="P25570cf" type="PETG" color="#F6DA5A" used_m="1.5" used_g="5"/>
  </plate>
  <plate>
    <metadata key="index" value="2"/>
    <metadata key="prediction" value="200"/>
    <metadata key="weight" value="20"/>
  </plate>
</config>
"""

_MODEL_SETTINGS = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <plate>
    <metadata key="plater_id" value="1"/>
    <metadata key="gcode_file" value="Metadata/plate_1.gcode"/>
    <metadata key="thumbnail_file" value="Metadata/plate_1.png"/>
    <metadata key="top_file" value="Metadata/top_1.png"/>
  </plate>
  <plate>
    <metadata key="plater_id" value="2"/>
    <metadata key="gcode_file" value="Metadata/plate_2.gcode"/>
    <metadata key="thumbnail_file" value="Metadata/plate_2.png"/>
    <metadata key="top_file" value="Metadata/top_2.png"/>
  </plate>
</config>
"""


def _global(slot: int, *, color: str, used_g: float) -> GlobalFilament:
    return GlobalFilament(
        slot=slot,
        ref=FilamentRef(slot=0, tray_info_idx="P25570cf", type="PETG", color=color),
        total_used_g=used_g,
    )


def test_slice_info_uses_global_slots_not_local() -> None:
    """核心契约：两个盘都用局部 slot 0，合并后必须是 id=1 与 id=2。"""
    filaments = [_global(0, color="#F6DA5A", used_g=10.0), _global(1, color="#FFFFFF", used_g=5.0)]

    result = rewrite_slice_info(
        _SLICE_INFO, prediction_s=300, weight_g=30.0, filaments=filaments
    )

    ids = re.findall(r'<filament id="(\d+)"', result)
    assert ids == ["1", "2"]
    assert len(set(ids)) == len(filaments)


def test_slice_info_is_single_plate_with_totals() -> None:
    result = rewrite_slice_info(
        _SLICE_INFO,
        prediction_s=300,
        weight_g=30.0,
        filaments=[_global(0, color="#F6DA5A", used_g=10.0)],
    )

    assert result.count("<plate>") == 1
    assert re.search(r'key="index" value="1"', result)
    assert re.search(r'key="prediction" value="300"', result)
    assert re.search(r'key="weight" value="30"', result)


def test_slice_info_uses_aggregated_usage() -> None:
    result = rewrite_slice_info(
        _SLICE_INFO,
        prediction_s=None,
        weight_g=None,
        filaments=[_global(0, color="#F6DA5A", used_g=12.5)],
    )

    assert 'used_g="12.50"' in result


def test_rewrite_model_settings_converges_to_single_plate() -> None:
    result = rewrite_model_settings(_MODEL_SETTINGS)

    assert result.count("<plate>") == 1
    assert 'key="plater_id" value="1"' in result
    assert 'key="gcode_file" value="Metadata/plate_1.gcode"' in result
    # 资源引用必须指向第 1 盘
    assert "plate_2" not in result
    assert "top_2" not in result


def test_rewrite_model_settings_rejects_missing_plate() -> None:
    with pytest.raises(MetadataError):
        rewrite_model_settings("<config></config>")


def test_rewrite_filament_sequence_keeps_only_plate_1() -> None:
    payload = '{"plate_1":{"sequence":[1]},"plate_2":{"sequence":[3]},"extra_key":1}'

    parsed = json.loads(rewrite_filament_sequence(payload, slots=2))

    assert list(parsed["plate_1"]["sequence"]) == [1, 2]
    assert "plate_2" not in parsed
    assert parsed["extra_key"] == 1


def test_rewrite_plate_json_updates_colors_and_ids() -> None:
    payload = '{"filament_colors":["#FFFFFF"],"filament_ids":["GFL99"],"bed_type":"textured_plate"}'

    parsed = json.loads(
        rewrite_plate_json(
            payload,
            filaments=[
                FilamentRef(slot=0, tray_info_idx="P25570cf", type="PETG", color="#F6DA5A"),
                FilamentRef(slot=1, tray_info_idx="GFL99", type="PLA", color="#FFFFFF"),
            ],
        )
    )

    assert parsed["filament_colors"] == ["#F6DA5A", "#FFFFFF"]
    assert parsed["filament_ids"] == ["P25570cf", "GFL99"]
    assert parsed["bed_type"] == "textured_plate"
