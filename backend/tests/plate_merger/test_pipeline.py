"""端到端流水线测试：用最小合法 3MF 验证打包、重写与校验。"""

from __future__ import annotations

import json
import re
import zipfile

import pytest

from app.plate_merger.errors import UnsupportedFormatError, ValidationError
from app.plate_merger.io3mf import CONTENT_TYPES, compute_md5, write_3mf
from app.plate_merger.models import MergeOptions
from app.plate_merger.pipeline import MergeRequest, merge
from app.plate_merger.presets import CONSERVATIVE

_CONTENT_TYPES = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'
)

_END_SEQUENCE = (
    "M621 S255\n"
    "M104 S0 ; turn off hotend\n"
    "M400\n"
    "G1 Z50 F600\n"
    ";=====printer finish  sound=========\n"
    "M1006 W\n"
    "M18 X Y Z\n"
    "M73 P100 R0\n"
)


def _gcode(plate_index: int) -> str:
    """构造一份最小但结构完整的切片 G-code（单耗材，局部槽位 0）。"""
    return (
        "; HEADER_BLOCK_START\n; HEADER_BLOCK_END\n"
        "; CONFIG_BLOCK_START\n; CONFIG_BLOCK_END\n"
        "; EXECUTABLE_BLOCK_START\n"
        f"G28\nG1 X{plate_index} Y{plate_index} F3000\nM620 S0A\nT1000\nM621 S0A\n"
        f"{_END_SEQUENCE}"
        "; EXECUTABLE_BLOCK_END\n"
    )


def _make_3mf(path, colors: list[str]) -> None:
    """按颜色列表生成一个多盘 3MF（每盘单耗材，局部槽位均为 0）。"""
    slice_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<config>",
        '<header><header_item key="X-BBL-Client-Version" value="02.05.03.61"/></header>',
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
        CONTENT_TYPES: _CONTENT_TYPES,
        "Metadata/slice_info.config": "\n".join(slice_lines).encode(),
        "Metadata/model_settings.config": "\n".join(model_lines).encode(),
        "Metadata/filament_sequence.json": json.dumps({"plate_1": {"sequence": [1]}}).encode(),
        "Metadata/plate_1.json": json.dumps(
            {"filament_colors": ["#FFFFFF"], "filament_ids": ["GFL99"]}
        ).encode(),
    }
    for index in range(1, len(colors) + 1):
        members[f"Metadata/plate_{index}.gcode"] = _gcode(index).encode()
        members[f"Metadata/plate_{index}.png"] = b"\x89PNG\r\n"

    write_3mf(path, members)


def _options() -> MergeOptions:
    return MergeOptions(swap_params=CONSERVATIVE)


def test_merge_three_plates_produces_single_plate_package(tmp_path) -> None:
    source = tmp_path / "multi.gcode.3mf"
    _make_3mf(source, ["#F6DA5A", "#FFFFFF", "#161616"])
    output = tmp_path / "merged.gcode.3mf"

    result = merge([MergeRequest(source, i) for i in (1, 2, 3)], options=_options(), output=output)

    assert result.plate_count == 3
    assert output.exists()

    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        plate_gcodes = [name for name in names if re.match(r"Metadata/plate_\d+\.gcode$", name)]
        assert plate_gcodes == ["Metadata/plate_1.gcode"]
        # 第 2、3 盘的位图应被清理
        assert not any(name in names for name in ("Metadata/plate_2.png", "Metadata/plate_3.png"))

        gcode = archive.read("Metadata/plate_1.gcode").decode()
        assert gcode.count(";start change plate") == 2
        assert gcode.count("; EXECUTABLE_BLOCK_END") == 1

        md5_text = archive.read("Metadata/plate_1.gcode.md5").decode().strip()
        assert md5_text == compute_md5(gcode.encode("utf-8"), upper=True)


def test_slice_info_filament_ids_are_global_and_unique(tmp_path) -> None:
    """三盘单耗材合并后必须得到 id=1/2/3，而不是三条 id=1。"""
    source = tmp_path / "multi.gcode.3mf"
    _make_3mf(source, ["#F6DA5A", "#FFFFFF", "#161616"])
    output = tmp_path / "merged.gcode.3mf"

    merge([MergeRequest(source, i) for i in (1, 2, 3)], options=_options(), output=output)

    with zipfile.ZipFile(output) as archive:
        slice_info = archive.read("Metadata/slice_info.config").decode()

    ids = re.findall(r'<filament id="(\d+)"', slice_info)
    assert ids == ["1", "2", "3"]
    assert len(set(ids)) == 3


def test_model_settings_points_to_merged_gcode(tmp_path) -> None:
    source = tmp_path / "multi.gcode.3mf"
    _make_3mf(source, ["#F6DA5A", "#FFFFFF"])
    output = tmp_path / "merged.gcode.3mf"

    merge([MergeRequest(source, 1), MergeRequest(source, 2)], options=_options(), output=output)

    with zipfile.ZipFile(output) as archive:
        model_settings = archive.read("Metadata/model_settings.config").decode()

    assert model_settings.count("<plate>") == 1
    assert 'key="gcode_file" value="Metadata/plate_1.gcode"' in model_settings


def test_gcode_slots_are_remapped_across_plates(tmp_path) -> None:
    source = tmp_path / "multi.gcode.3mf"
    _make_3mf(source, ["#F6DA5A", "#FFFFFF"])
    output = tmp_path / "merged.gcode.3mf"

    merge([MergeRequest(source, 1), MergeRequest(source, 2)], options=_options(), output=output)

    with zipfile.ZipFile(output) as archive:
        gcode = archive.read("Metadata/plate_1.gcode").decode()

    assert "M620 S0A" in gcode
    assert "M620 S1A" in gcode


def test_rejects_input_that_already_contains_swap_code(tmp_path) -> None:
    # 两盘合盘才会注入换盘码；单盘产物不含标记，无法用于本用例
    source = tmp_path / "already.gcode.3mf"
    _make_3mf(source, ["#F6DA5A", "#FFFFFF"])
    merged = tmp_path / "merged.gcode.3mf"
    merge([MergeRequest(source, 1), MergeRequest(source, 2)], options=_options(), output=merged)

    # 用产物再次合盘必须被拒绝，避免叠加换盘码
    with pytest.raises(ValidationError):
        merge([MergeRequest(merged, 1)], options=_options(), output=tmp_path / "again.gcode.3mf")


def test_rejects_missing_plate(tmp_path) -> None:
    source = tmp_path / "multi.gcode.3mf"
    _make_3mf(source, ["#F6DA5A"])

    with pytest.raises(ValidationError):
        merge([MergeRequest(source, 9)], options=_options(), output=tmp_path / "out.gcode.3mf")


def test_rejects_unsliced_package(tmp_path) -> None:
    source = tmp_path / "project.3mf"
    write_3mf(source, {CONTENT_TYPES: _CONTENT_TYPES, "3D/3dmodel.model": b"<model/>"})

    with pytest.raises(UnsupportedFormatError):
        merge([MergeRequest(source, 1)], options=_options(), output=tmp_path / "out.gcode.3mf")


def test_output_removed_when_verification_fails(tmp_path, monkeypatch) -> None:
    """校验失败时不得留下坏包。"""
    source = tmp_path / "multi.gcode.3mf"
    _make_3mf(source, ["#F6DA5A", "#FFFFFF"])
    output = tmp_path / "merged.gcode.3mf"

    from app.plate_merger import pipeline

    monkeypatch.setattr(pipeline, "verify_package", lambda *args, **kwargs: _report_with_failure())

    with pytest.raises(Exception):
        merge([MergeRequest(source, 1), MergeRequest(source, 2)], options=_options(), output=output)

    assert not output.exists()


def _report_with_failure():
    from app.plate_merger.verifier import CheckResult, VerificationReport

    return VerificationReport(checks=(CheckResult(name="forced", passed=False, detail="forced"),))
