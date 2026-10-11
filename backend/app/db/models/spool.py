from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, Index, Integer, Numeric, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime


class Spool(Base):
    __tablename__ = "spools"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    material: Mapped[str] = mapped_column(Text, nullable=False)
    color: Mapped[str] = mapped_column(Text, nullable=False)
    brand: Mapped[str | None] = mapped_column(Text, nullable=True)

    diameter_mm: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False, default=1.75)

    initial_grams: Mapped[int] = mapped_column(Integer, nullable=False)
    tare_grams: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_total: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    price_per_kg: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    remaining_grams_est: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=datetime.utcnow)


Index("ix_spools_status", Spool.status)
