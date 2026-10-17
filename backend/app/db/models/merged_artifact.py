"""合盘产物记录。

解决的问题
----------
合盘（``POST /plate-merger/merge``）本来只产出文件，系统里没有任何记录，
导致：
1. 任务页看不到这次生产；
2. 下发的 G-code 与耗材扣减无法关联；
3. 「产物 → 下发 → 进度 → 扣料 → 报告」链条断在合盘这一步。

本表把每次合盘登记为一条 artifact，下发时关联打印机与打印任务
（``print_jobs`` 仍由 event_processor 按 MQTT 上报创建，避免重复建任务）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Float, ForeignKey, Index, Integer, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from app.db.base import Base
from app.db.types import UTCDateTime


class MergedArtifact(Base):
    __tablename__ = "merged_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)

    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    md5: Mapped[str | None] = mapped_column(Text, nullable=True)

    plate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_time_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_weight_g: Mapped[float | None] = mapped_column(Float, nullable=True)

    #: 全局槽位清单 ``[{slot, type, color, total_used_g, plates}]``
    filaments_json: Mapped[list] = mapped_column(JSON, nullable=False, server_default=text("'[]'"))
    #: 来源文件 ``[{name, plate, time_s, weight_g}]``
    sources_json: Mapped[list] = mapped_column(JSON, nullable=False, server_default=text("'[]'"))
    #: 合盘参数快照（预设 / 策略 / 音效 / 冷却）
    options_json: Mapped[dict] = mapped_column(JSON, nullable=False, server_default=text("'{}'"))

    #: draft（已生成未下发）/ dispatched / printing / completed / failed
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")

    printer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("printers.id", ondelete="SET NULL"), nullable=True
    )
    #: 关联打印任务；由 event_processor 创建后回填
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("print_jobs.id", ondelete="SET NULL"), nullable=True
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=datetime.utcnow)


Index(
    "ux_merged_artifacts_file_name",
    MergedArtifact.file_name,
    unique=True,
)
Index("ix_merged_artifacts_created_at", MergedArtifact.created_at)
