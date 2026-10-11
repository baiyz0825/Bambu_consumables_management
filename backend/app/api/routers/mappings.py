"""托盘 ↔ 耗材卷绑定路由。

支持绑定到 MaterialStock（推荐）或 Spool（legacy）。
绑定逻辑：同一 printer+tray 的旧激活记录先解绑（unbound_at = now），
再插入新记录，保证部分唯一索引 (unbound_at IS NULL) 不冲突。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.models.material_stock import MaterialStock
from app.db.models.printer import Printer
from app.db.models.spool import Spool
from app.db.models.tray_mapping import TrayMapping
from app.schemas.mapping import TrayMappingCreate, TrayMappingOut, TrayMappingUnbind
from app.services.tray_service import bind_tray_to_stock

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tray-mappings", tags=["tray-mappings"])


@router.get("", response_model=list[TrayMappingOut])
async def list_mappings(
    printer_id: UUID | None = Query(default=None),
    active_only: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """列出托盘绑定记录，关联返回 MaterialStock 摘要。"""
    stmt = select(TrayMapping, MaterialStock).outerjoin(
        MaterialStock, TrayMapping.stock_id == MaterialStock.id
    )
    if printer_id is not None:
        stmt = stmt.where(TrayMapping.printer_id == printer_id)
    if active_only:
        stmt = stmt.where(TrayMapping.unbound_at.is_(None))
    stmt = stmt.order_by(TrayMapping.bound_at.desc())

    rows = (await db.execute(stmt)).all()
    return [
        {
            "id": tm.id,
            "printer_id": tm.printer_id,
            "tray_id": tm.tray_id,
            "stock_id": tm.stock_id,
            "spool_id": tm.spool_id,
            "bound_at": tm.bound_at,
            "unbound_at": tm.unbound_at,
            "stock_material": stock.material if stock else None,
            "stock_color": stock.color if stock else None,
            "stock_brand": stock.brand if stock else None,
            "stock_remaining_grams": stock.remaining_grams if stock else None,
        }
        for tm, stock in rows
    ]


@router.post("", response_model=TrayMappingOut)
async def bind_mapping(body: TrayMappingCreate, db: AsyncSession = Depends(get_db)) -> dict:
    """绑定托盘到耗材库存项（或 legacy Spool）。

    自动解绑同一 printer+tray 的旧激活记录。
    """
    if not await db.get(Printer, body.printer_id):
        raise HTTPException(status_code=404, detail="printer not found")

    # 校验绑定目标存在
    stock = None
    if body.stock_id:
        stock = await db.get(MaterialStock, body.stock_id)
        if not stock:
            raise HTTPException(status_code=404, detail="stock not found")
    if body.spool_id:
        if not await db.get(Spool, body.spool_id):
            raise HTTPException(status_code=404, detail="spool not found")

    now = datetime.now(timezone.utc)

    if body.stock_id:
        # 推荐路径：复用领域服务（内部处理旧激活记录的解绑）
        m = await bind_tray_to_stock(
            db, printer_id=body.printer_id, tray_id=body.tray_id, stock_id=body.stock_id, now=now
        )
        await db.commit()
        await db.refresh(m)
    else:
        # legacy 路径：绑定到 Spool（仅向后兼容，新绑定请用 stock_id）
        await db.execute(
            update(TrayMapping)
            .where(
                TrayMapping.printer_id == body.printer_id,
                TrayMapping.tray_id == body.tray_id,
                TrayMapping.unbound_at.is_(None),
            )
            .values(unbound_at=now)
        )
        m = TrayMapping(
            printer_id=body.printer_id,
            tray_id=body.tray_id,
            stock_id=None,
            spool_id=body.spool_id,
            bound_at=now,
            unbound_at=None,
        )
        db.add(m)
        await db.commit()
        await db.refresh(m)

    logger.info(
        "tray bound: printer=%s tray=%d stock_id=%s spool_id=%s",
        body.printer_id, body.tray_id, body.stock_id, body.spool_id,
    )

    return {
        "id": m.id,
        "printer_id": m.printer_id,
        "tray_id": m.tray_id,
        "stock_id": m.stock_id,
        "spool_id": m.spool_id,
        "bound_at": m.bound_at,
        "unbound_at": m.unbound_at,
        "stock_material": stock.material if stock else None,
        "stock_color": stock.color if stock else None,
        "stock_brand": stock.brand if stock else None,
        "stock_remaining_grams": stock.remaining_grams if stock else None,
    }


@router.post("/unbind")
async def unbind_mapping(body: TrayMappingUnbind, db: AsyncSession = Depends(get_db)) -> dict:
    """解绑托盘（幂等：不存在激活绑定也返回 ok）。"""
    if not await db.get(Printer, body.printer_id):
        raise HTTPException(status_code=404, detail="printer not found")

    now = datetime.now(timezone.utc)
    await db.execute(
        update(TrayMapping)
        .where(
            TrayMapping.printer_id == body.printer_id,
            TrayMapping.tray_id == body.tray_id,
            TrayMapping.unbound_at.is_(None),
        )
        .values(unbound_at=now)
    )
    await db.commit()
    return {"ok": True}
