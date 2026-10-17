"""采集端归一化与事件推导的回归测试。

这些字段直接决定数字孪生能表现什么（温度、层高、风扇、灯、故障定位），
因此每新增一个字段都要有测试兜底，避免固件字段类型变化时静默失效。
"""

from __future__ import annotations

from collector.main import (
    _derive_event_type,
    _hms_signature,
    _hms_to_ecode,
    _normalize_event_from_payload,
    _normalize_hms,
)


def _payload(**print_fields) -> dict:
    base: dict = {"gcode_state": "RUNNING", "mc_percent": 42}
    base.update(print_fields)
    return {"print": base}


def test_temperature_and_layer_fields() -> None:
    n = _normalize_event_from_payload(
        _payload(
            nozzle_temper=215.6,
            nozzle_target_temper=220.0,
            bed_temper=60.1,
            bed_target_temper=60.0,
            layer_num=125,
            total_layer_num=250,
        )
    )
    assert n is not None
    assert n["nozzle_temper"] == 215.6
    assert n["nozzle_target_temper"] == 220.0
    assert n["bed_temper"] == 60.1
    assert n["bed_target_temper"] == 60.0
    assert n["layer_num"] == 125
    assert n["total_layer_num"] == 250


def test_fan_and_speed_accept_string_values() -> None:
    # 固件把风扇转速 / 速度档上报为字符串，不能只按 int 解析
    n = _normalize_event_from_payload(
        _payload(
            cooling_fan_speed="128",
            big_fan1_speed="80",
            heatbreak_fan_speed="255",
            spd_lvl="2",
            spd_mag="100",
        )
    )
    assert n is not None
    assert n["cooling_fan_speed"] == 128
    assert n["big_fan1_speed"] == 80
    assert n["heatbreak_fan_speed"] == 255
    assert n["spd_lvl"] == 2
    assert n["spd_mag"] == 100


def test_lights_report_flattened() -> None:
    n = _normalize_event_from_payload(
        _payload(
            lights_report=[
                {"node": "chamber_light", "mode": "on"},
                {"node": "work_light", "mode": "off"},
            ]
        )
    )
    assert n is not None
    assert n["lights"] == {"chamber_light": "on", "work_light": "off"}


def test_tray_transition_fields() -> None:
    n = _normalize_event_from_payload(
        _payload(
            ams={
                "tray_now": "0",
                "tray_pre": "2",
                "tray_tar": "1",
                "tray": [{"id": "0", "tray_type": "PETG", "tray_color": "F6DA5AFF"}],
            }
        )
    )
    assert n is not None
    assert n["tray_now"] == 0
    assert n["tray_pre"] == 2
    assert n["tray_tar"] == 1


def test_hms_ecode_composition() -> None:
    # ecode = attr(4 位 hex) + code(4 位 hex)
    assert _hms_to_ecode(1795, 32786) == "07038012"
    assert _hms_to_ecode(7, 0x8012) == "00078012"
    assert _hms_to_ecode(None, 1) is None
    assert _hms_to_ecode(1, None) is None


def test_hms_normalized_with_module_prefix() -> None:
    items = _normalize_hms(
        {
            "hms": [
                {"attr": 1795, "code": 32786, "action": 0, "timestamp": 1761352945},
                {"attr": 1285, "code": 32785},
            ]
        }
    )
    # 输出按 ecode 排序，保证签名稳定
    assert [item["ecode"] for item in items] == ["05058011", "07038012"]
    assert items[0]["module"] == "05"
    assert items[1]["module"] == "07"
    assert items[1]["action"] == 0


def test_hms_signature_none_when_empty() -> None:
    assert _hms_signature({"hms": []}) is None
    assert _hms_signature({}) is None
    sig = _hms_signature({"hms": [{"ecode": "07038012"}]})
    assert isinstance(sig, str) and len(sig) == 64


def test_event_type_hms_takes_priority() -> None:
    sig = "a" * 64
    # 故障出现：gcode_state 可能仍是 RUNNING，只靠状态机发现不了
    assert _derive_event_type("RUNNING", "RUNNING", sig, None) == "HmsError"
    # 同一故障持续：走原去重逻辑
    assert _derive_event_type("RUNNING", "RUNNING", sig, sig) == "PrintProgress"
    # 故障清除
    assert _derive_event_type("RUNNING", "RUNNING", None, sig) == "HmsCleared"


def test_event_type_state_machine_unchanged() -> None:
    assert _derive_event_type("RUNNING", "IDLE", None, None) == "PrintStarted"
    assert _derive_event_type("FINISH", "RUNNING", None, None) == "PrintEnded"
    assert _derive_event_type("FAILED", "RUNNING", None, None) == "PrintFailed"
    assert _derive_event_type("RUNNING", "RUNNING", None, None) == "PrintProgress"


def test_missing_fields_do_not_break_normalization() -> None:
    n = _normalize_event_from_payload({"print": {"gcode_state": "IDLE"}})
    assert n is not None
    assert n["nozzle_temper"] is None
    assert n["layer_num"] is None
    assert n["hms"] == []
    assert n["lights"] == {}
    assert n["tray_pre"] is None
