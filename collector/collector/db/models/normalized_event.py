from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, JSON, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from collector.db.base import Base
from collector.db.types import UTCDateTime, sqlite_biginteger_pk


class NormalizedEvent(Base):
    __tablename__ = "normalized_events"

    id: Mapped[int] = mapped_column(sqlite_biginteger_pk(), primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(Text, nullable=False)
    printer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("printers.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    data_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    raw_event_id: Mapped[int | None] = mapped_column(ForeignKey("raw_events.id", ondelete="SET NULL"), nullable=True)
    # 与 backend 模型保持一致（SQLite 模式下两端都可能建表，schema 必须对齐）
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=datetime.utcnow)
