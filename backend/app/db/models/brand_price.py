from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BrandPrice(Base):
    """每种耗材品牌一条单价，单位是元/千克。"""

    __tablename__ = "brand_prices"
    __table_args__ = (
        CheckConstraint("price_per_kg >= 0", name="ck_brand_prices_price_per_kg_ge_0"),
    )

    brand: Mapped[str] = mapped_column(Text, primary_key=True)
    price_per_kg: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=_utcnow)
