from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, JSON, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime, sqlite_biginteger_pk


class NormalizedEvent(Base):
    __tablename__ = "normalized_events"

    id: Mapped[int] = mapped_column(sqlite_biginteger_pk(), primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    printer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("printers.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    data_json: Mapped[dict] = mapped_column(JSON, nullable=False)

    raw_event_id: Mapped[int | None] = mapped_column(ForeignKey("raw_events.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=datetime.utcnow)


Index("ix_normalized_events_printer_id_occurred_at", NormalizedEvent.printer_id, NormalizedEvent.occurred_at)
Index("ix_normalized_events_type", NormalizedEvent.type)
