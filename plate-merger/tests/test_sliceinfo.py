"""3MF 元数据解析测试：覆盖槽位基准转换、颜色规范化与容错。"""

from __future__ import annotations

import pytest

from plate_merger.errors import MetadataError
from plate_merger.sliceinfo import (
    parse_filament_sequence,
    parse_plate_json,
    parse_project_settings,
    parse_slice_info,
)

_SLICE_INFO = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <header>
    <header_item key="X-BBL-Client-Type" value="slicer"/>
    <header_item key="X-BBL-Client-Version" value="02.08.02.61"/>
  </header>
  <plate>
    <metadata key="index" value="1"/>
    <metadata key="prediction" value="7391"/>
    <metadata key="weight" value="42.1"/>
    <filament id="2" tray_info_idx="P25570cf" type="PETG" color="#F6DA5A" used_m="3.03" used_g="9.03"/>
    <filament id="5" tray_info_idx="GFL99" type="PLA" color="FFFFFFFF" used_m="1.0" used_g="3.0"/>
    <object name="demo"/>
  </plate>
  <plate>
    <metadata key="index" value="2"/>
    <metadata key="prediction" value="100"/>
  </plate>
</config>
"""


def test_parse_header_client_version() -> None:
    info = parse_slice_info(_SLICE_INFO)

    assert info.header.client_version == "02.08.02.61"
    assert info.header.client_type == "slicer"


def test_parse_plates_sorted_by_index() -> None:
    info = parse_slice_info(_SLICE_INFO)

    assert [plate.index for plate in info.plates] == [1, 2]
    assert info.plate(1) is not None
    assert info.plate(99) is None


def test_parse_prediction_and_weight() -> None:
    plate = parse_slice_info(_SLICE_INFO).plate(1)

    assert plate is not None
    assert plate.prediction_s == 7391
    assert plate.weight_g == pytest.approx(42.1)


def test_filament_id_is_converted_to_zero_based_slot() -> None:
    """用非连续、乱序的 id 才能证明真的做了 1-based -> 0-based 转换。"""
    plate = parse_slice_info(_SLICE_INFO).plate(1)

    assert plate is not None
    assert [filament.slot for filament in plate.filaments] == [1, 4]


def test_filament_color_is_normalized() -> None:
    plate = parse_slice_info(_SLICE_INFO).plate(1)

    assert plate is not None
    assert plate.filaments[0].color == "#F6DA5A"
    # 8 位 RRGGBBAA 取前六位
    assert plate.filaments[1].color == "#FFFFFF"


def test_plate_without_filaments_is_allowed() -> None:
    plate = parse_slice_info(_SLICE_INFO).plate(2)

    assert plate is not None
    assert plate.filaments == ()
    assert plate.prediction_s == 100


def test_invalid_xml_raises_metadata_error() -> None:
    with pytest.raises(MetadataError):
        parse_slice_info("<config>")


def test_wrong_root_raises_metadata_error() -> None:
    with pytest.raises(MetadataError):
        parse_slice_info("<not_config/>")


def test_parse_plate_json() -> None:
    payload = (
        '{"filament_colors":["#FF8040"],"filament_ids":["GFL99"],'
        '"bed_type":"textured_plate","first_extruder":0,"is_seq_print":false}'
    )

    parsed = parse_plate_json(payload)

    assert parsed.filament_colors == ("#FF8040",)
    assert parsed.filament_ids == ("GFL99",)
    assert parsed.bed_type == "textured_plate"
    assert parsed.first_extruder == 0
    assert parsed.is_seq_print is False


def test_parse_plate_json_invalid() -> None:
    with pytest.raises(MetadataError):
        parse_plate_json("not json")


def test_parse_filament_sequence() -> None:
    payload = '{"plate_1":{"sequence":[1]},"plate_2":{"sequence":[3]},"other":{}}'

    sequence = parse_filament_sequence(payload)

    assert sequence == {1: (1,), 2: (3,)}


def test_parse_project_settings_passes_unknown_keys() -> None:
    payload = '{"filament_colour":["#FFFFFF"],"brand_new_key":123}'

    settings = parse_project_settings(payload)

    assert settings["filament_colour"] == ["#FFFFFF"]
    assert settings["brand_new_key"] == 123


def test_parse_project_settings_invalid() -> None:
    with pytest.raises(MetadataError):
        parse_project_settings("[]")


def test_filament_requires_valid_id() -> None:
    """缺少 id 属格式异常，不能静默用位置索引顶替。"""
    xml = '<config><plate><metadata key="index" value="1"/><filament tray_info_idx="GFL99"/></plate></config>'

    with pytest.raises(MetadataError):
        parse_slice_info(xml)


def test_filament_unknown_attributes_are_preserved() -> None:
    """新版本新增的属性必须透传，便于后续统计 AMS 上下料时间。"""
    xml = (
        '<config><plate><metadata key="index" value="1"/>'
        '<filament id="1" tray_info_idx="GFL99" total_load_time="12"/>'
        "</plate></config>"
    )

    plate = parse_slice_info(xml).plates[0]

    assert plate.filaments[0].extra == {"total_load_time": "12"}


def test_plate_index_zero_is_not_treated_as_missing() -> None:
    xml = '<config><plate><metadata key="index" value="0"/></plate></config>'

    assert parse_slice_info(xml).plates[0].index == 0


def test_is_seq_print_accepts_string_false() -> None:
    parsed = parse_plate_json('{"is_seq_print":"false"}')

    assert parsed.is_seq_print is False


def test_filament_colors_must_be_list() -> None:
    with pytest.raises(MetadataError):
        parse_plate_json('{"filament_colors":"FF8040"}')
