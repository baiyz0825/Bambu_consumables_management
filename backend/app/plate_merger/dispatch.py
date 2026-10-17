"""下发打印：FTPS 上传 + MQTT 启动任务。

参数全部来自**实机验证结论**（技术方案 §8.3），四个易错点已固化在此：

1. 上传目标必须是 FTP **根目录**，不能写 ``/cache/``；
2. ``url`` 必须是 ``ftp:///文件名.3mf``，不带 ``/cache/`` 前缀；
3. ``project_id`` / ``profile_id`` / ``task_id`` / ``subtask_id`` 本地打印固定 ``"0"`` 且必填；
4. ``bed_levelling`` 是**英式双 l**（写成 ``bed_leveling`` 会被静默忽略）。

依赖说明：FTPS 用标准库 ``ftplib``；MQTT 用 ``paho-mqtt``（可选依赖）。
未安装时抛 :class:`PlateMergerError` 并给出安装提示，而不是 ImportError 裸奔。
"""

from __future__ import annotations

import hashlib
import json
import ssl
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import PlateMergerError

#: 合盘产物的 G-code 成员名
_GCODE_MEMBER = "Metadata/plate_1.gcode"


@dataclass(frozen=True)
class PrinterTarget:
    """打印机连接参数。"""

    host: str
    access_code: str
    serial: str
    ftp_port: int = 990
    mqtt_port: int = 8883
    timeout_s: float = 10.0


@dataclass(frozen=True)
class DispatchResult:
    """下发结果。"""

    accepted: bool
    detail: str
    remote_name: str = ""
    report: dict[str, Any] | None = None


def build_project_file_command(
    *,
    remote_name: str,
    md5: str,
    subtask_name: str,
    use_ams: bool = False,
    ams_mapping: str = "",
    bed_type: str = "auto",
    bed_levelling: bool = False,
    timelapse: bool = False,
) -> dict[str, Any]:
    """构造 ``project_file`` 命令体。"""
    return {
        "print": {
            "sequence_id": "0",
            "command": "project_file",
            "param": _GCODE_MEMBER,
            "project_id": "0",
            "profile_id": "0",
            "task_id": "0",
            "subtask_id": "0",
            "subtask_name": subtask_name,
            "file": "",
            "url": f"ftp:///{remote_name}",
            "md5": md5.lower(),
            "timelapse": timelapse,
            "bed_type": bed_type,
            "bed_levelling": bed_levelling,
            "flow_cali": False,
            "vibration_cali": False,
            "layer_inspect": False,
            "ams_mapping": ams_mapping,
            "use_ams": use_ams,
        }
    }


def package_md5(package_path: str | Path) -> str:
    """计算包内 G-code 的 MD5（大写入设备时使用小写，与固件校验一致）。"""
    from .io3mf import ThreeMfPackage, compute_md5

    with ThreeMfPackage.open(package_path) as package:
        names = dict(package.plate_gcodes())
        if not names:
            raise PlateMergerError("包内没有 G-code", detail={"path": str(package_path)})
        data = package.read(names[min(names)])
    return compute_md5(data, upper=False)


def upload_package(package_path: str | Path, target: PrinterTarget) -> str:
    """通过隐式 TLS 的 FTPS 上传到打印机根目录。

    :return: 远程文件名。
    :raises PlateMergerError: 连接或上传失败。
    """
    import ftplib

    path = Path(package_path)
    if not path.is_file():
        raise PlateMergerError("待上传文件不存在", detail={"path": str(path)})

    context = ssl._create_unverified_context()
    ftp = ftplib.FTP_TLS(context=context, timeout=target.timeout_s)
    try:
        ftp.connect(target.host, target.ftp_port)
        # Bambu 使用隐式 TLS：连接建立后立刻包装 socket
        ftp.sock = context.wrap_socket(ftp.sock)
        # secure=False 避免发送服务器不认识的 AUTH TLS
        ftp.login("bblp", target.access_code, secure=False)
        ftp.prot_p()
        with path.open("rb") as handle:
            ftp.storbinary(f"STOR {path.name}", handle)
    except (OSError, ftplib.all_errors) as exc:  # type: ignore[attr-defined]
        raise PlateMergerError("FTPS 上传失败", detail={"host": target.host, "reason": str(exc)}) from exc
    finally:
        try:
            ftp.quit()
        except Exception:  # noqa: BLE001 - 关闭失败不影响结果
            pass

    return path.name


def dispatch(
    package_path: str | Path,
    target: PrinterTarget,
    *,
    subtask_name: str | None = None,
    use_ams: bool = False,
    ams_mapping: str = "",
    bed_type: str = "auto",
    bed_levelling: bool = False,
    timelapse: bool = False,
    wait_s: float = 15.0,
) -> DispatchResult:
    """上传并启动打印。

    :param wait_s: 命令发出后监听状态的最长时间（秒）。
    :raises PlateMergerError: 上传失败、缺少 MQTT 依赖或连接失败。
    """
    remote_name = upload_package(package_path, target)
    digest = package_md5(package_path)
    command = build_project_file_command(
        remote_name=remote_name,
        md5=digest,
        subtask_name=subtask_name or Path(package_path).stem,
        use_ams=use_ams,
        ams_mapping=ams_mapping,
        bed_type=bed_type,
        bed_levelling=bed_levelling,
        timelapse=timelapse,
    )

    report = _publish_and_wait(target, command, wait_s=wait_s)
    state = str(report.get("gcode_state") or "")
    error = report.get("print_error") or 0
    accepted = state in {"RUNNING", "PREPARE"} and not error
    detail = f"state={state or 'unknown'} print_error={error} hms={report.get('hms') or []}"
    return DispatchResult(accepted=accepted, detail=detail, remote_name=remote_name, report=report)


def _publish_and_wait(target: PrinterTarget, command: dict[str, Any], *, wait_s: float) -> dict[str, Any]:
    """发布命令并收集打印机上报的最新状态。"""
    try:
        import paho.mqtt.client as mqtt
    except ImportError as exc:
        raise PlateMergerError(
            "下发需要 MQTT 客户端库",
            detail={"hint": 'pip install "plate-merger[dispatch]"'},
        ) from exc

    report: dict[str, Any] = {}

    def on_connect(client, userdata, flags, reason_code, properties=None) -> None:  # noqa: ANN001
        client.subscribe(f"device/{target.serial}/report")
        client.publish(f"device/{target.serial}/request", json.dumps(command))

    def on_message(client, userdata, message) -> None:  # noqa: ANN001
        try:
            payload = json.loads(message.payload)
        except (ValueError, TypeError):
            return
        print_object = payload.get("print") if isinstance(payload, dict) else None
        if isinstance(print_object, dict):
            report.update(print_object)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
    client.on_connect = on_connect
    client.on_message = on_message
    client.username_pw_set("bblp", target.access_code)
    client.tls_set(cert_reqs=ssl.CERT_NONE)
    client.tls_insecure_set(True)

    try:
        client.connect(target.host, target.mqtt_port, keepalive=60)
    except OSError as exc:
        raise PlateMergerError("MQTT 连接失败", detail={"host": target.host, "reason": str(exc)}) from exc

    client.loop_start()
    try:
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            if str(report.get("gcode_state") or "") in {"RUNNING", "PREPARE"}:
                break
            if report.get("print_error"):
                break
            time.sleep(0.5)
    finally:
        client.loop_stop()
        client.disconnect()

    return report


def verify_md5_consistency(package_path: str | Path, remote_md5: str) -> bool:
    """辅助函数：比对本地计算值与待发送值，便于单测与排障。"""
    local = hashlib.md5(Path(package_path).read_bytes()).hexdigest()
    return local == remote_md5
