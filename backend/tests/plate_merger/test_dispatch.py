"""下发命令构造测试（离线部分，不接触打印机）。"""

from __future__ import annotations

from app.plate_merger.dispatch import build_project_file_command


def _command(**overrides):
    payload = {
        "remote_name": "plate_merged.3mf",
        "md5": "ABCDEF0123456789",
        "subtask_name": "demo",
    }
    payload.update(overrides)
    return build_project_file_command(**payload)["print"]


def test_url_points_to_ftp_root_without_cache_prefix() -> None:
    """实测结论：url 必须带三个斜杠且不带 /cache/。"""
    assert _command()["url"] == "ftp:///plate_merged.3mf"


def test_required_zero_ids_are_present() -> None:
    command = _command()

    for key in ("project_id", "profile_id", "task_id", "subtask_id"):
        assert command[key] == "0"


def test_bed_levelling_uses_british_spelling() -> None:
    """写成 bed_leveling 会被固件静默忽略。"""
    command = _command()

    assert "bed_levelling" in command
    assert "bed_leveling" not in command


def test_param_points_to_merged_gcode() -> None:
    assert _command()["param"] == "Metadata/plate_1.gcode"


def test_md5_is_lowercase() -> None:
    assert _command(md5="ABCDEF")["md5"] == "abcdef"


def test_ams_fields_follow_arguments() -> None:
    command = _command(use_ams=True, ams_mapping="0,1")

    assert command["use_ams"] is True
    assert command["ams_mapping"] == "0,1"


def test_calibration_flags_default_off() -> None:
    command = _command()

    assert command["flow_cali"] is False
    assert command["vibration_cali"] is False
    assert command["layer_inspect"] is False
    assert command["timelapse"] is False
