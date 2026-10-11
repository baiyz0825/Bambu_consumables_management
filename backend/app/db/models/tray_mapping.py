"""托盘 ↔ 耗材卷绑定模型。

支持两种绑定：
- stock_id：绑定到 MaterialStock（推荐，按材质+颜色+品牌聚合的库存项）
- spool_id：绑定到 Spool（legacy，具体一卷，向后兼容）

两种绑定可共存（同一托盘的历史记录），但同一时刻同一托盘只能有一个激活绑定
（unbound_at IS NULL 的部分唯一索引保证）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.db.base import Base
from app.db.types import UTCDateTime, sqlite_biginteger_pk


class TrayMapping(Base):
    __tablename__ = "tray_mappings"

    id: Mapped[int] = mapped_column(sqlite_biginteger_pk(), primary_key=True, autoincrement=True)
    printer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("printers.id", ondelete="CASCADE"), nullable=False
    )
    tray_id: Mapped[int] = mapped_column(Integer, nullable=False)

    # 绑定到 MaterialStock（推荐）：按材质+颜色+品牌聚合的库存项
    stock_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("material_stocks.id", ondelete="SET NULL"), nullable=True
    )
    # 绑定到 Spool（legacy，具体一卷）：向后兼容，新绑定建议用 stock_id
    spool_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("spools.id", ondelete="SET NULL"), nullable=True
    )

    bound_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=datetime.utcnow)
    unbound_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


Index("ix_tray_mappings_printer_id_tray_id", TrayMapping.printer_id, TrayMapping.tray_id)
Index("ix_tray_mappings_stock_id", TrayMapping.stock_id)
Index("ix_tray_mappings_spool_id", TrayMapping.spool_id)
Index(
    "ux_tray_mappings_active_printer_tray",
    TrayMapping.printer_id,
    TrayMapping.tray_id,
    unique=True,
    postgresql_where=text("unbound_at IS NULL"),
    sqlite_where=text("unbound_at IS NULL"),
)
