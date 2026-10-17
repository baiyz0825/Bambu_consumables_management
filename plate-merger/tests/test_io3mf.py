"""3MF 读写层测试：覆盖大小写、OPC 规范、可复现性与异常路径。"""

from __future__ import annotations

import zipfile

import pytest

from plate_merger.errors import InvalidPackageError
from plate_merger.io3mf import CONTENT_TYPES, ThreeMfPackage, compute_md5, write_3mf

_CT_XML = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'
)


def _sample_members() -> dict[str, bytes]:
    """构造一个最小可用的 3MF 成员集合。"""
    return {
        CONTENT_TYPES: _CT_XML,
        "Metadata/plate_1.gcode": b"G28\nG1 X0 Y0\n",
        "Metadata/plate_2.gcode": b"G28\n",
        "Metadata/slice_info.config": b"<config/>",
    }


def test_compute_md5_is_uppercase_by_default() -> None:
    assert compute_md5(b"abc") == "900150983CD24FB0D6963F7D28E17F72"


def test_compute_md5_supports_lowercase() -> None:
    assert compute_md5(b"abc", upper=False) == "900150983cd24fb0d6963f7d28e17f72"


def test_roundtrip_and_plate_detection(tmp_path) -> None:
    output = write_3mf(tmp_path / "a.3mf", _sample_members())

    with ThreeMfPackage.open(output) as package:
        assert package.is_plate_sliced()
        assert package.plate_gcodes() == [
            (1, "Metadata/plate_1.gcode"),
            (2, "Metadata/plate_2.gcode"),
        ]
        assert package.read_text("Metadata/plate_1.gcode").startswith("G28")


def test_opc_content_types_is_first_and_stored(tmp_path) -> None:
    output = write_3mf(tmp_path / "b.3mf", _sample_members(), opc_pack=True)

    with zipfile.ZipFile(output) as archive:
        infos = archive.infolist()
        assert infos[0].filename == CONTENT_TYPES
        assert infos[0].compress_type == zipfile.ZIP_STORED
        assert all(info.compress_type == zipfile.ZIP_DEFLATED for info in infos[1:])


def test_opc_requires_content_types(tmp_path) -> None:
    members = {name: data for name, data in _sample_members().items() if name != CONTENT_TYPES}

    with pytest.raises(InvalidPackageError):
        write_3mf(tmp_path / "c.3mf", members, opc_pack=True)


def test_member_lookup_is_case_insensitive(tmp_path) -> None:
    output = write_3mf(tmp_path / "d.3mf", _sample_members())

    with ThreeMfPackage.open(output) as package:
        assert package.has("metadata/PLATE_1.GCODE")
        assert package.resolve("Metadata/PLATE_2.gcode") == "Metadata/plate_2.gcode"


def test_missing_member_raises(tmp_path) -> None:
    output = write_3mf(tmp_path / "e.3mf", _sample_members())

    with ThreeMfPackage.open(output) as package, pytest.raises(InvalidPackageError):
        package.read("Metadata/not_exist.config")


def test_output_is_byte_deterministic(tmp_path) -> None:
    """相同输入必须产生相同字节，保证回归测试与缓存有效。"""
    first = write_3mf(tmp_path / "f1.3mf", _sample_members())
    second = write_3mf(tmp_path / "f2.3mf", _sample_members())

    assert first.read_bytes() == second.read_bytes()


def test_open_missing_file_raises(tmp_path) -> None:
    with pytest.raises(InvalidPackageError):
        ThreeMfPackage.open(tmp_path / "nope.3mf")


def test_open_non_zip_raises(tmp_path) -> None:
    bad = tmp_path / "bad.3mf"
    bad.write_bytes(b"not a zip")

    with pytest.raises(InvalidPackageError):
        ThreeMfPackage.open(bad)


def test_member_order_does_not_affect_output_bytes(tmp_path) -> None:
    """成员输入顺序不同也必须产出相同字节，否则 md5 会漂移。"""
    members = _sample_members()
    reversed_members = dict(reversed(list(members.items())))

    first = write_3mf(tmp_path / "o1.3mf", members)
    second = write_3mf(tmp_path / "o2.3mf", reversed_members)

    assert first.read_bytes() == second.read_bytes()


def test_read_text_is_strict_but_lossy_variant_works(tmp_path) -> None:
    members = _sample_members()
    members["Metadata/bad.txt"] = b"\xff\xfe\x00"
    output = write_3mf(tmp_path / "bad-text.3mf", members)

    with ThreeMfPackage.open(output) as package:
        with pytest.raises(InvalidPackageError):
            package.read_text("Metadata/bad.txt")
        assert package.read_text_lossy("Metadata/bad.txt")
