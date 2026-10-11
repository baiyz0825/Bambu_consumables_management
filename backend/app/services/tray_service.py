"""托盘（料盘/料槽）相关领域服务。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.material_ledger import MaterialLedger
from app.db.models.tray_mapping import TrayMapping

logger = logging.getLogger(__name__)


async def get_total_trays(db: AsyncSession) -> int:
    """统计料盘总数（账本 tray_delta 累计）。"""
    total = await db.scalar(select(func.coalesce(func.sum(MaterialLedger.tray_delta), 0)))
    return int(total or 0)


async def bind_tray_to_stock(
    db: AsyncSession,
    *,
    printer_id: UUID,
    tray_id: int,
    stock_id: UUID,
    now: datetime | None = None,
) -> TrayMapping:
    """把托盘绑定到库存项（幂等覆盖）。

    同一 printer+tray 同时只能有一个激活绑定（由部分唯一索引
    ``ux_tray_mappings_active_printer_tray`` 保证），因此先解绑旧的激活记录，
    再插入新记录。调用方需自行校验 printer/stock 是否存在。

    Args:
        db: 数据库会话
        printer_id: 打印机 ID
        tray_id: AMS 托盘编号
        stock_id: 目标库存项 ID
        now: 绑定时刻（默认当前 UTC 时间）

    Returns:
        新建的 TrayMapping 记录（已 flush，未 commit）
    """
    ts = now or datetime.now(timezone.utc)

    await db.execute(
        update(TrayMapping)
        .where(
            TrayMapping.printer_id == printer_id,
            TrayMapping.tray_id == int(tray_id),
            TrayMapping.unbound_at.is_(None),
        )
        .values(unbound_at=ts)
    )

    mapping = TrayMapping(
        printer_id=printer_id,
        tray_id=int(tray_id),
        stock_id=stock_id,
        spool_id=None,
        bound_at=ts,
        unbound_at=None,
    )
    db.add(mapping)
    await db.flush()

    logger.info(
        "tray bound via service: printer=%s tray=%d stock=%s",
        printer_id, tray_id, stock_id,
    )
    return mapping


async def unbind_trays_by_stock(
    db: AsyncSession,
    *,
    stock_id: UUID,
    now: datetime | None = None,
) -> int:
    """解绑所有指向该库存项的激活托盘绑定。

    库存归档或合并后会停止参与扣减，此时应同步解绑，避免前端仍显示
    「已绑定」、而结算实际已回落自动匹配造成认知不一致。

    Args:
        db: 数据库会话
        stock_id: 库存项 ID
        now: 解绑时刻（默认当前 UTC 时间）

    Returns:
        解绑的记录数
    """
    ts = now or datetime.now(timezone.utc)
    res = await db.execute(
        update(TrayMapping)
        .where(TrayMapping.stock_id == stock_id, TrayMapping.unbound_at.is_(None))
        .values(unbound_at=ts)
    )
    count = int(res.rowcount or 0)
    if count:
        logger.info("unbound %d tray mapping(s) for archived stock=%s", count, stock_id)
    return count
