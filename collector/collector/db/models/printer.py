from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from collector.db.base import Base
from collector.db.types import UTCDateTime


class Printer(Base):
    __tablename__ = "printers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True)
    ip: Mapped[str] = mapped_column(Text, nullable=False)
    serial: Mapped[str] = mapped_column(Text, nullable=False)
    alias: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    lan_access_code_enc: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    last_seen: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # 与 backend 模型保持一致（SQLite 模式下两端都可能建表，schema 必须对齐）
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=datetime.utcnow)
