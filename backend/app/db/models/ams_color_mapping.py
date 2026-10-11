from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Index, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import UTCDateTime


class AmsColorMapping(Base):
    __tablename__ = "ams_color_mappings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    # Canonicalized AMS color hex, e.g. "#FFFFFF"
    color_hex: Mapped[str] = mapped_column(Text, nullable=False)
    # Human-friendly name used as stock matching key, e.g. "白色"
    color_name: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=datetime.utcnow)


Index("ux_ams_color_mappings_hex", AmsColorMapping.color_hex, unique=True)
