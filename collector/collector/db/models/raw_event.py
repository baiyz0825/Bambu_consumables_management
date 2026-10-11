from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, JSON, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from collector.db.base import Base
from collector.db.types import UTCDateTime, sqlite_biginteger_pk


class RawEvent(Base):
    __tablename__ = "raw_events"

    id: Mapped[int] = mapped_column(sqlite_biginteger_pk(), primary_key=True, autoincrement=True)
    printer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("printers.id", ondelete="CASCADE"), nullable=False
    )
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
