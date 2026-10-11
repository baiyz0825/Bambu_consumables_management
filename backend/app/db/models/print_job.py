from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, JSON, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.db.base import Base
from app.db.types import UTCDateTime


class PrintJob(Base):
    __tablename__ = "print_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    printer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("printers.id", ondelete="CASCADE"), nullable=False
    )

    job_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    spool_binding_snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, server_default=text("'{}'"))

    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=datetime.utcnow)


Index("ix_print_jobs_printer_id_started_at", PrintJob.printer_id, PrintJob.started_at)
Index(
    "ux_print_jobs_printer_job_key",
    PrintJob.printer_id,
    PrintJob.job_key,
    unique=True,
    postgresql_where=text("job_key IS NOT NULL"),
    sqlite_where=text("job_key IS NOT NULL"),
)
