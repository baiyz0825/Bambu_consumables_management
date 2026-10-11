from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime


class InventoryAdjustment(Base):
    __tablename__ = "inventory_adjustments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    spool_id: Mapped[uuid.UUID] = mapped_column(Uuid(), ForeignKey("spools.id", ondelete="RESTRICT"), nullable=False)
    delta_grams: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=datetime.utcnow)


Index("ix_inventory_adjustments_spool_id", InventoryAdjustment.spool_id)
