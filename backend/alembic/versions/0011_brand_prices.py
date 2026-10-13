"""Brand unit prices (yuan per kilogram)

每种品牌一条单价，供消耗报告按克估算成本。

Revision ID: 0011_brand_prices
Revises: 0010_cloud_session
Create Date: 2026-10-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0011_brand_prices"
down_revision: Union[str, None] = "0010_cloud_session"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "brand_prices",
        sa.Column("brand", sa.Text(), primary_key=True),
        sa.Column("price_per_kg", sa.Numeric(10, 2), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("price_per_kg >= 0", name="ck_brand_prices_price_per_kg_ge_0"),
    )


def downgrade() -> None:
    op.drop_table("brand_prices")
