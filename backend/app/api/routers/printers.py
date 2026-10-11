from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
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


