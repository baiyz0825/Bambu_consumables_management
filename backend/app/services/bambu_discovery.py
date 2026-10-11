"""拓竹打印机局域网 mDNS 扫描服务。

拓竹打印机通过 mDNS/Bonjour 广播自身存在，服务类型为
``_bambu-discovery._tcp.local.``。每台打印机会在 mDNS 的 TXT 记录中
携带设备信息（序列号、型号、固件版本、版本号等）。

本模块用 zeroconf 库在局域网内监听该服务类型，收集一定时间窗口内
发现的所有设备，返回结构化列表供前端展示和一键添加。

注意：
- mDNS 只能发现 IP / hostname / 序列号 / 型号，**无法获取 LAN Access Code**
  （访问码在打印机屏幕上显示，需用户手动输入）
- 扫描是同步阻塞操作，调用方应通过 ``asyncio.to_thread`` 在线程池执行
"""

from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass, field
from typing import Any

from zeroconf import DNSCache, ServiceInfo, ServiceListener, Zeroconf

logger = logging.getLogger(__name__)

# 拓竹打印机的 mDNS 服务类型
BAMBU_SERVICE_TYPE = "_bambu-discovery._tcp.local."

# 扫描默认超时（秒）
DEFAULT_SCAN_TIMEOUT = 5.0


@dataclass
class DiscoveredPrinter:
    """扫描发现的打印机信息。"""

    ip: str
    port: int
    hostname: str
    serial: str | None = None
    model: str | None = None
    fw_version: str | None = None
    api_version: str | None = None
    name: str | None = None
    properties: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ip": self.ip,
            "port": self.port,
            "hostname": self.hostname,
            "serial": self.serial,
            "model": self.model,
            "fw_version": self.fw_version,
            "api_version": self.api_version,
            "name": self.name,
            "properties": self.properties,
        }


class _BambuListener(ServiceListener):
    """zeroconf 服务监听器，收集所有 _bambu-discovery._tcp 服务。"""

    def __init__(self) -> None:
        self.devices: dict[str, DiscoveredPrinter] = {}

    def add_service(self, zc: Zeroconf, service_type: str, name: str) -> None:
        # zeroconf 0.39+ 用 update_service 合并了 add/update；旧版 add 触发一次 get_info
        self._resolve(zc, name)

    def update_service(self, zc: Zeroconf, service_type: str, name: str) -> None:
        self._resolve(zc, name)

    def remove_service(self, zc: Zeroconf, service_type: str, name: str) -> None:
        # 服务下线，从列表移除（key 用 name 去 . 后缀）
        key = name.removesuffix("." + service_type)
        self.devices.pop(key, None)

    def _resolve(self, zc: Zeroconf, name: str) -> None:
        try:
            info: ServiceInfo = zc.get_service_info(BAMBU_SERVICE_TYPE, name, timeout=2000)
        except Exception as e:
            logger.debug("resolve %s failed: %s", name, e)
            return
        if info is None:
            return

        # 提取 IP（取第一个有效地址）
        addresses = info.parsed_addresses()
        ip = addresses[0] if addresses else None
        if not ip:
            return

        # 解析 TXT 记录
        props: dict[str, str] = {}
        if info.properties:
            for k, v in info.properties.items():
                key = k.decode("utf-8", errors="replace") if isinstance(k, bytes) else str(k)
                val = v.decode("utf-8", errors="replace") if isinstance(v, bytes) else ("" if v is None else str(v))
                props[key] = val

        # 拓竹 TXT 字段：id（序列号）、model、version（固件）、api_ver
        serial = props.get("id") or props.get("serial")
        model = props.get("model")
        fw_version = props.get("version") or props.get("firmware_version")
        api_version = props.get("api_ver")

        # hostname 去 .local. 后缀，方便展示
        hostname = (info.server or name).removesuffix(".local.").removesuffix(".")

        key = name.removesuffix("." + BAMBU_SERVICE_TYPE)
        device = DiscoveredPrinter(
            ip=ip,
            port=int(info.port) if info.port else 0,
            hostname=hostname,
            serial=serial,
            model=model,
            fw_version=fw_version,
            api_version=api_version,
            name=key,
            properties=props,
        )
        self.devices[key] = device
        logger.info("discovered bambu printer: ip=%s serial=%s model=%s", ip, serial, model)


def scan_bambu_printers(timeout: float = DEFAULT_SCAN_TIMEOUT) -> list[dict[str, Any]]:
    """扫描局域网内的拓竹打印机。

    同步阻塞调用，建议通过 ``asyncio.to_thread(scan_bambu_printers, timeout)`` 使用。

    Args:
        timeout: 扫描持续时间（秒），默认 5 秒

    Returns:
        发现的打印机列表（dict），按 IP 排序
    """
    listener = _BambuListener()
    zc = None
    try:
        # 指定 cache 避免某些环境下 DNSCache 缺失
        zc = Zeroconf()
        zc.add_service_listener(BAMBU_SERVICE_TYPE, listener)
        # 阻塞等待扫描窗口
        time.sleep(timeout)
    except Exception as e:
        logger.warning("mDNS scan failed: %s", e)
    finally:
        if zc is not None:
            try:
                zc.remove_service_listener(listener)
                zc.close()
            except Exception:
                pass

    devices = list(listener.devices.values())
    # 按 IP 排序，方便前端展示稳定
    devices.sort(key=lambda d: _ip_sort_key(d.ip))
    return [d.to_dict() for d in devices]


def _ip_sort_key(ip: str) -> tuple:
    """IP 排序键：把 IPv4 按数值排序。"""
    try:
        return tuple(int(p) for p in ip.split("."))
    except Exception:
        return (999,)


def is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """快速探测端口是否开放（用于扫描后验证 MQTT 8883 可达）。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False
