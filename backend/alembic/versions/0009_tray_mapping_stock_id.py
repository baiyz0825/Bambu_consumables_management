"""Tray mapping bind to material stock

新增 ``tray_mappings.stock_id``（外键到 ``material_stocks``）以支撑「AMS 机内托盘
手动绑定耗材库」；同时把 ``spool_id`` 放宽为可空（新绑定走 stock_id，legacy 列仅
兼容历史数据）。

Revision ID: 0009_tray_stock_id
Revises: 0008_timezone_fix
Create Date: 2025-12-22 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0009_tray_stock_id'
down_revision: Union[str, None] = '0008_timezone_fix'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch_alter_table 保证 SQLite（重建表）与 PostgreSQL（原生 ALTER）都能执行
    with op.batch_alter_table("tray_mappings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("stock_id", sa.Uuid(), nullable=True))
        batch_op.alter_column("spool_id", existing_type=sa.Uuid(), nullable=True)
        batch_op.create_foreign_key(
            "fk_tray_mappings_stock_id_material_stocks",
            "material_stocks",
            ["stock_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            batch_op.f("ix_tray_mappings_stock_id"), ["stock_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("tray_mappings", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_tray_mappings_stock_id"))
        batch_op.drop_constraint(
            "fk_tray_mappings_stock_id_material_stocks", type_="foreignkey"
        )
        batch_op.drop_column("stock_id")
        # 说明：spool_id 不回退为 NOT NULL —— 存量行可能已是只绑定 stock_id 的记录，
        # 强行收紧会导致 downgrade 失败；保持可空语义与模型一致即可。
