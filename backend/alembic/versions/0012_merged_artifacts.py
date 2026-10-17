"""合盘产物记录表

把每次合盘登记为一条 artifact，打通「产物 → 下发 → 任务 → 扣料」链路。

Revision ID: 0012_merged_artifacts
Revises: 0011_brand_prices
Create Date: 2026-10-17 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012_merged_artifacts"
down_revision: Union[str, None] = "0011_brand_prices"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "merged_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("md5", sa.Text(), nullable=True),
        sa.Column("plate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_time_s", sa.Integer(), nullable=True),
        sa.Column("total_weight_g", sa.Float(), nullable=True),
        sa.Column("filaments_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("sources_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("options_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column(
            "printer_id",
            sa.Uuid(),
            sa.ForeignKey("printers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("print_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ux_merged_artifacts_file_name",
        "merged_artifacts",
        ["file_name"],
        unique=True,
    )
    op.create_index("ix_merged_artifacts_created_at", "merged_artifacts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_merged_artifacts_created_at", table_name="merged_artifacts")
    op.drop_index("ux_merged_artifacts_file_name", table_name="merged_artifacts")
    op.drop_table("merged_artifacts")
