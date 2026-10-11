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
    spool_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("spools.id", ondelete="RESTRICT"), nullable=False
    )

    bound_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=datetime.utcnow)
    unbound_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


Index("ix_tray_mappings_printer_id_tray_id", TrayMapping.printer_id, TrayMapping.tray_id)
Index("ix_tray_mappings_spool_id", TrayMapping.spool_id)
Index(
    "ux_tray_mappings_active_printer_tray",
    TrayMapping.printer_id,
    TrayMapping.tray_id,
    unique=True,
    postgresql_where=text("unbound_at IS NULL"),
    sqlite_where=text("unbound_at IS NULL"),
)
