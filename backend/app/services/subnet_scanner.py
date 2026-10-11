"""局域网网段扫描（mDNS 不可用时的兜底发现手段）。

为什么需要它：
    部分网络环境（AP 隔离、跨 VLAN、组播被禁、打印机未开启 mDNS 广播）下
    mDNS 扫描拿不到任何设备，但打印机 IP 本身可达（可 ping / 可连 8883）。
    此时按网段并发探测 MQTT 端口（拓竹局域网模式固定 8883）即可定位设备。

设计要点：
- 纯 TCP 连接探测，不发送任何业务报文，对打印机无副作用；
- asyncio + 信号量并发，254 个地址可在数秒内完成；
- 每个地址探测首个连通端口即返回，避免无谓等待；
- 同时提供反向 DNS 解析（best-effort），便于前端展示主机名。
"""

from __future__ import annotations

import asyncio
import logging
import socket
from dataclasses import dataclass, field
from typing import Any, Iterable

logger = logging.getLogger(__name__)

#: 拓竹打印机局域网 MQTT（TLS）端口
BAMBU_MQTT_PORT = 8883

#: 默认探测端口列表：先 MQTT，其次常见 HTTP（部分型号/第三方网关开放）
DEFAULT_PORTS: tuple[int, ...] = (BAMBU_MQTT_PORT,)

#: 单个地址的连接超时（秒）
DEFAULT_CONNECT_TIMEOUT = 0.35

#: 并发探测上限，避免瞬间打开过多 socket
DEFAULT_CONCURRENCY = 96


@dataclass
class ProbeResult:
    """单个主机的探测结果。"""

    ip: str
    reachable: bool
    open_ports: list[int] = field(default_factory=list)
    hostname: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ip": self.ip,
            "reachable": self.reachable,
            "open_ports": self.open_ports,
            "hostname": self.hostname,
        }


def host_ipv4() -> str | None:
    """获取本机用于访问外网的 IPv4 地址（不实际发包）。

    Returns:
        本机 IPv4 字符串；无法确定时返回 None
    """
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # UDP connect 不发数据包，仅用于让内核选择出口地址
        sock.connect(("223.5.5.5", 80))
        return sock.getsockname()[0]
    except OSError:
        logger.debug("cannot determine host IPv4 address")
        return None
    finally:
        if sock is not None:
            sock.close()


def suggested_subnet() -> str | None:
    """推断本机所在网段前缀（前三段，按 /24 处理）。

    Returns:
        形如 ``"192.168.9"`` 的网段前缀；无法确定时返回 None
    """
    ip = host_ipv4()
    if not ip:
        return None
    parts = ip.split(".")
    if len(parts) != 4:
        return None
    return ".".join(parts[:3])


def parse_subnet(subnet: str) -> list[str]:
    """把网段描述展开为待探测的 IP 列表。

    支持三种输入：
    - ``"192.168.9"`` / ``"192.168.9.0/24"``：展开 1-254
    - ``"192.168.9.10-192.168.9.80"``：按末段范围展开
    - ``"192.168.9.37"``：单个 IP

    Args:
        subnet: 网段或 IP 描述

    Returns:
        待探测 IP 列表（升序、去重）

    Raises:
        ValueError: 输入格式非法
    """
    s = str(subnet).strip()
    if not s:
        raise ValueError("网段/地址不能为空")

    # 单 IP
    if s.count(".") == 3 and "/" not in s and "-" not in s:
        _validate_ipv4(s)
        return [s]

    # CIDR：仅支持 /24（常见家庭/办公网段）
    if "/" in s:
        net, _, mask = s.partition("/")
        _validate_ipv4(net)
        if mask != "24":
            raise ValueError("当前仅支持 /24 网段扫描")
        prefix = ".".join(net.split(".")[:3])
        return [f"{prefix}.{i}" for i in range(1, 255)]

    # 范围：192.168.9.10-192.168.9.80
    if "-" in s:
        start, _, end = s.partition("-")
        start, end = start.strip(), end.strip()
        _validate_ipv4(start)
        _validate_ipv4(end)
        sp, ep = start.split("."), end.split(".")
        if sp[:3] != ep[:3]:
            raise ValueError("范围扫描需在同一 /24 网段内")
        lo, hi = int(sp[3]), int(ep[3])
        if lo > hi:
            lo, hi = hi, lo
        prefix = ".".join(sp[:3])
        return [f"{prefix}.{i}" for i in range(max(lo, 1), min(hi, 254) + 1)]

    # 网段前缀：192.168.9
    parts = s.split(".")
    if len(parts) == 3 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return [f"{s}.{i}" for i in range(1, 255)]

    raise ValueError("无法识别的网段格式，示例：192.168.9 或 192.168.9.0/24")


def _validate_ipv4(ip: str) -> None:
    """校验 IPv4 字符串合法性，非法时抛 ValueError。"""
    parts = str(ip).split(".")
    if len(parts) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        raise ValueError(f"非法 IPv4 地址：{ip}")


async def _probe_one(
    ip: str,
    ports: Iterable[int],
    timeout: float,
    resolve_hostname: bool,
    sem: asyncio.Semaphore,
) -> ProbeResult:
    """探测单个 IP 的端口连通性。

    Args:
        ip: 目标地址
        ports: 待探测端口列表
        timeout: 单端口连接超时（秒）
        resolve_hostname: 是否反查主机名
        sem: 并发信号量

    Returns:
        探测结果；全部端口不可达时 reachable=False
    """
    open_ports: list[int] = []
    async with sem:
        for port in ports:
            try:
                reader_writer = await asyncio.wait_for(
                    asyncio.open_connection(ip, port), timeout=timeout
                )
            except (OSError, asyncio.TimeoutError):
                continue
            else:
                open_ports.append(port)
                writer = reader_writer[1]
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:  # noqa: BLE001 - 关闭失败不影响探测结论
                    pass
                # 首个端口连通即可判定为在线设备，无需继续探测
                break

    hostname: str | None = None
    if open_ports and resolve_hostname:
        hostname = await asyncio.to_thread(_reverse_dns, ip)

    return ProbeResult(ip=ip, reachable=bool(open_ports), open_ports=open_ports, hostname=hostname)


def _reverse_dns(ip: str) -> str | None:
    """反向解析主机名（失败返回 None，不抛异常）。"""
    try:
        return socket.gethostbyaddr(ip)[0]
    except OSError:
        return None


async def scan_subnet(
    subnet: str,
    ports: Iterable[int] = DEFAULT_PORTS,
    timeout: float = DEFAULT_CONNECT_TIMEOUT,
    concurrency: int = DEFAULT_CONCURRENCY,
    resolve_hostname: bool = True,
) -> list[dict[str, Any]]:
    """并发探测网段内开放指定端口的主机。

    Args:
        subnet: 网段描述，见 :func:`parse_subnet`
        ports: 探测端口列表
        timeout: 单端口连接超时（秒）
        concurrency: 并发上限
        resolve_hostname: 是否反查主机名（会略微增加耗时）

    Returns:
        可达主机列表（dict），按 IP 数值升序
    """
    ips = parse_subnet(subnet)
    port_list = list(ports) or list(DEFAULT_PORTS)
    sem = asyncio.Semaphore(max(1, concurrency))

    logger.info("subnet scan started: subnet=%s hosts=%d ports=%s", subnet, len(ips), port_list)

    results = await asyncio.gather(
        *(_probe_one(ip, port_list, timeout, resolve_hostname, sem) for ip in ips),
        return_exceptions=True,
    )

    reachable: list[ProbeResult] = []
    for r in results:
        if isinstance(r, BaseException):
            logger.debug("probe skipped: %s", r)
            continue
        if r.reachable:
            reachable.append(r)

    reachable.sort(key=lambda r: _ip_sort_key(r.ip))
    logger.info("subnet scan finished: subnet=%s reachable=%d", subnet, len(reachable))
    return [r.to_dict() for r in reachable]


def _ip_sort_key(ip: str) -> tuple:
    """IP 排序键：把 IPv4 按数值升序排列。"""
    try:
        return tuple(int(p) for p in ip.split("."))
    except Exception:  # noqa: BLE001 - 非法 IP 排到最后
        return (999,)
