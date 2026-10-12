"""云端设备按序列号并入已有打印机，不产生第二条。"""

from types import SimpleNamespace

from app.services.bambu_cloud import describe_cloud_devices


def test_same_serial_is_one_printer():
    local = {"01S000000000001": SimpleNamespace(id="printer-1", alias="工作室 P1S", serial="01S000000000001")}
    devices = [
        {"dev_id": "01S000000000001", "name": "P1S", "dev_product_name": "P1S", "online": True},
        {"dev_id": "01S000000000002", "name": "客厅 A1", "dev_product_name": "A1", "online": False},
    ]
    rows = describe_cloud_devices(devices, local)
    assert rows[0]["same_printer"] is True
    assert rows[0]["printer_id"] == "printer-1"
    assert rows[0]["printer_alias"] == "工作室 P1S"
    assert rows[1]["same_printer"] is False
    assert rows[1]["printer_id"] is None


if __name__ == "__main__":
    test_same_serial_is_one_printer()
    print("ok")
