"""Cloud account session and printer link_used

同一台打印机仍是 printers 里的一行。云端账号单独存一份会话，
采集端按序列号复用该行，能直连时走局域网。

Revision ID: 0010_cloud_session
Revises: 0009_tray_stock_id
Create Date: 2026-10-12 20:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010_cloud_session"
down_revision: Union[str, None] = "0009_tray_stock_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bambu_cloud_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("region", sa.Text(), nullable=False),
        sa.Column("access_token_enc", sa.Text(), nullable=False),
        sa.Column("refresh_token_enc", sa.Text(), nullable=False, server_default=""),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uid", sa.Text(), nullable=True),
        sa.Column("mqtt_username", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.add_column(
        "printers",
        sa.Column("link_used", sa.Text(), nullable=False, server_default="unknown"),
    )


def downgrade() -> None:
    op.drop_column("printers", "link_used")
    op.drop_table("bambu_cloud_sessions")
