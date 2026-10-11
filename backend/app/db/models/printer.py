from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Index, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime


class Printer(Base):
    __tablename__ = "printers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    ip: Mapped[str] = mapped_column(Text, nullable=False)
    serial: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    alias: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 加密存储（Fernet），避免明文落库
    lan_access_code_enc: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(Text, nullable=False, default="unknown")
    last_seen: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=datetime.utcnow)


Index("ix_printers_serial", Printer.serial, unique=True)
