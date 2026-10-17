"""版本指纹测试。"""

from __future__ import annotations

import json

from _fixtures import make_3mf

from plate_merger.fingerprint import diff, probe


def test_probe_reads_client_version_and_plate_count(tmp_path) -> None:
    source = make_3mf(tmp_path / "a.3mf", ["#F6DA5A", "#FFFFFF"])

    fingerprint = probe(source)

    assert fingerprint.client_version == "02.05.03.61"
    assert fingerprint.plate_count == 2
    assert fingerprint.has_executable_block is True


def test_probe_collects_structure_keys(tmp_path) -> None:
    source = make_3mf(tmp_path / "a.3mf", ["#F6DA5A"])

    fingerprint = probe(source)

    assert "index" in fingerprint.slice_info_keys
    assert "prediction" in fingerprint.slice_info_keys
    assert fingerprint.project_settings_key_count == 5
    assert "bed_type" in fingerprint.filament_attrs


def test_probe_detects_template_version(tmp_path) -> None:
    source = make_3mf(tmp_path / "a.3mf", ["#F6DA5A"])

    assert "20251031" in probe(source).template_versions


def test_fingerprint_serializes_to_dict(tmp_path) -> None:
    source = make_3mf(tmp_path / "a.3mf", ["#F6DA5A"])

    payload = probe(source).to_dict()

    # 元组必须转成 list 才能 JSON 序列化
    assert isinstance(payload["slice_info_keys"], list)
    json.dumps(payload)


def test_diff_reports_version_change(tmp_path) -> None:
    base = probe(make_3mf(tmp_path / "a.3mf", ["#F6DA5A"]))
    current = probe(make_3mf(tmp_path / "b.3mf", ["#F6DA5A"], client_version="02.08.02.61"))

    changes = diff(base, current)

    assert any("客户端版本" in item for item in changes)


def test_diff_is_empty_for_identical_files(tmp_path) -> None:
    base = probe(make_3mf(tmp_path / "a.3mf", ["#F6DA5A"]))
    current = probe(make_3mf(tmp_path / "b.3mf", ["#F6DA5A"]))

    assert diff(base, current) == ()
