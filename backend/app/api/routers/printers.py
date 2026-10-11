from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings
from app.core.crypto import encrypt_str
from app.db.models.printer import Printer
from app.db.models.normalized_event import NormalizedEvent
from app.schemas.printer import PrinterCreate, PrinterDetail, PrinterOut, PrinterUpdate
from app.services.bambu_discovery import scan_bambu_printers
from app.services.subnet_scanner import (
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_PORTS,
    host_ipv4,
    scan_subnet,
    suggested_subnet,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/printers", tags=["printers"])


@router.get("/scan", response_model=None)
async def scan_printers(
    timeout: float = Query(default=5.0, ge=1.0, le=15.0, description="扫描持续时间（秒）"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """局域网 mDNS 扫描拓竹打印机。

    扫描窗口结束后返回发现的设备列表，并标记哪些已存在于数据库
    （已添加的不会重复添加）。前端可点击未添加的设备一键预填表单。

    注意：mDNS 只能发现 IP/Serial/Model，**LAN Access Code 需用户在打印机
    屏幕查看并手动输入**。
    """
    # mDNS 扫描是同步阻塞操作，放到线程池执行
    devices = await asyncio.to_thread(scan_bambu_printers, timeout)

    # 标记已添加的（按 serial 匹配）
    existing_serials: set[str] = set()
    if devices:
        serials = [d["serial"] for d in devices if d.get("serial")]
        if serials:
            rows = (
                await db.execute(select(Printer.serial).where(Printer.serial.in_(serials)))
            ).scalars().all()
            existing_serials = set(rows)

    for d in devices:
        d["already_added"] = d.get("serial") in existing_serials if d.get("serial") else False

    return {
        "count": len(devices),
        "devices": devices,
        "scan_timeout_seconds": timeout,
        "scan_mode": "mdns",
    }


class SubnetScanRequest(BaseModel):
    """网段扫描请求。

    subnet 为空时自动使用后端所在网段（/24）。
    """

    subnet: str | None = Field(default=None, description="网段或 IP，如 192.168.9 / 192.168.9.0/24 / 192.168.9.37")
    ports: list[int] | None = Field(default=None, description="探测端口列表，默认 8883（MQTT）")
    timeout: float | None = Field(default=None, ge=0.1, le=3.0, description="单端口连接超时（秒）")
    resolve_hostname: bool = Field(default=True, description="是否反查主机名")


@router.get("/network-info", response_model=None)
async def network_info() -> dict:
    """返回后端所在主机的 IP 与建议扫描网段，供前端预填网段输入框。

    注意：后端运行在 Docker/服务器 上时，返回的是**服务端**网段；
    若浏览器与服务端不在同一网段，用户需手动输入。
    """
    return {
        "host_ip": host_ipv4(),
        "suggested_subnet": suggested_subnet(),
    }


@router.post("/scan-subnet", response_model=None)
async def scan_subnet_printers(
    body: SubnetScanRequest = SubnetScanRequest(),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """按网段并发探测拓竹打印机（mDNS 不可用时的兜底方案）。

    通过 TCP 连接探测 8883（局域网 MQTT）端口判断设备是否在线，
    适用于 AP 隔离 / 组播被禁 / 打印机未广播 mDNS 的网络环境。

    端口探测只能确认「设备在线」，**序列号与 LAN Access Code 仍需用户手输**。
    """
    subnet = (body.subnet or "").strip() or suggested_subnet()
    if not subnet:
        raise HTTPException(
            status_code=400,
            detail="无法确定本机网段，请手动输入（如 192.168.9）",
        )

    try:
        hosts = await scan_subnet(
            subnet,
            ports=body.ports or DEFAULT_PORTS,
            timeout=body.timeout or DEFAULT_CONNECT_TIMEOUT,
            resolve_hostname=body.resolve_hostname,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 标记已添加的（按 IP 匹配）
    existing_ips: set[str] = set()
    if hosts:
        rows = (
            await db.execute(select(Printer.ip).where(Printer.ip.in_([h["ip"] for h in hosts])))
        ).scalars().all()
        existing_ips = set(rows)

    for h in hosts:
        h["already_added"] = h["ip"] in existing_ips

    return {
        "subnet": subnet,
        "count": len(hosts),
        "devices": hosts,
        "scan_mode": "subnet",
    }


@router.get("", response_model=list[PrinterOut])
async def list_printers(db: AsyncSession = Depends(get_db)) -> list[Printer]:
    return (await db.execute(select(Printer).order_by(Printer.created_at.desc()))).scalars().all()


@router.post("", response_model=PrinterDetail)
async def create_printer(body: PrinterCreate, db: AsyncSession = Depends(get_db)) -> Printer:
    p = Printer(
        ip=body.ip,
        serial=body.serial,
        alias=body.alias,
        model=body.model,
        lan_access_code_enc=encrypt_str(settings.app_secret_key, body.lan_access_code),
        status="unknown",
        last_seen=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(p)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="printer serial already exists")
    await db.refresh(p)
    return p


@router.get("/{printer_id}", response_model=PrinterDetail)
async def get_printer(printer_id: UUID, db: AsyncSession = Depends(get_db)) -> Printer:
    p = await db.get(Printer, printer_id)
    if not p:
        raise HTTPException(status_code=404, detail="printer not found")
    return p


@router.get("/{printer_id}/latest-report")
async def latest_report(printer_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    p = await db.get(Printer, printer_id)
    if not p:
        raise HTTPException(status_code=404, detail="printer not found")

    ev = (
        await db.execute(
            select(NormalizedEvent)
            .where(NormalizedEvent.printer_id == printer_id)
            .order_by(NormalizedEvent.occurred_at.desc(), NormalizedEvent.id.desc())
            .limit(1)
        )
    ).scalars().first()

    return {
        "printer_id": str(printer_id),
        "event": ev.data_json if ev else None,
        "type": ev.type if ev else None,
        "event_id": ev.event_id if ev else None,
        "occurred_at": ev.occurred_at.isoformat() if ev else None,
    }


@router.patch("/{printer_id}", response_model=PrinterDetail)
async def update_printer(printer_id: UUID, body: PrinterUpdate, db: AsyncSession = Depends(get_db)) -> Printer:
    p = await db.get(Printer, printer_id)
    if not p:
        raise HTTPException(status_code=404, detail="printer not found")

    if body.ip is not None:
        p.ip = body.ip
    if body.serial is not None:
        p.serial = body.serial
    if body.alias is not None:
        p.alias = body.alias
    if body.model is not None:
        p.model = body.model
    if body.lan_access_code is not None:
        p.lan_access_code_enc = encrypt_str(settings.app_secret_key, body.lan_access_code)

    p.updated_at = datetime.now(timezone.utc)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="printer serial already exists")
    await db.refresh(p)
    return p


@router.delete("/{printer_id}")
async def delete_printer(printer_id: UUID, db: AsyncSession = Depends(get_db)) -> dict:
    p = await db.get(Printer, printer_id)
    if not p:
        raise HTTPException(status_code=404, detail="printer not found")
    await db.delete(p)
    await db.commit()
    return {"ok": True}


