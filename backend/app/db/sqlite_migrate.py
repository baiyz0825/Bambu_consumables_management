"""SQLite 单机模式的幂等结构补齐。

背景：SQLite 模式通过 ``create_all(checkfirst=True)`` 建表，已存在的旧表不会被
自动升级。当模型新增列或放宽约束时（例如 ``tray_mappings`` 增加 ``stock_id``、
``spool_id`` 改为可空），需要一次轻量迁移把老库对齐到当前模型。

设计原则：
- 幂等：每次启动都可安全执行，结构已对齐时直接跳过；
- 最小侵入：只处理明确登记过的表，不改动其他表；
- 可观测：每个分支都有日志记录，失败时抛错由调用方决定降级策略。
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.engine import Connection

logger = logging.getLogger(__name__)


def _table_columns(sync_conn: Connection, table: str) -> dict[str, dict]:
    """读取 SQLite 表结构：列名 -> {type, notnull, pk}。表不存在时返回空字典。"""
    rows = sync_conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    # PRAGMA table_info 列序: cid, name, type, notnull, dflt_value, pk
    return {
        str(r[1]): {"type": r[2], "notnull": int(r[3] or 0), "pk": int(r[5] or 0)}
        for r in rows
    }


def _table_exists(sync_conn: Connection, table: str) -> bool:
    """判断表是否存在（用于清理上次迁移失败的中间态）。"""
    row = sync_conn.execute(
        text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :t"),
        {"t": table},
    ).fetchone()
    return row is not None


def ensure_tray_mapping_schema(sync_conn: Connection) -> None:
    """把 ``tray_mappings`` 对齐到当前模型（新增 stock_id、spool_id 放宽为可空）。

    SQLite 不支持 ``ALTER COLUMN`` 修改约束，因此结构不匹配时采用
    「清理中间态 -> 删除旧索引 -> 旧表改名 -> 按模型建新表 -> 迁移数据 -> 删除旧表」
    的重建流程。旧索引必须先删除：``ALTER TABLE RENAME`` 后索引名仍被旧表占用，
    会导致新表同名索引创建失败。
    """
    cols = _table_columns(sync_conn, "tray_mappings")
    if not cols:
        # 表还不存在：由 create_all 负责创建，这里无需处理
        return

    need_stock_id = "stock_id" not in cols
    spool_notnull = cols.get("spool_id", {}).get("notnull", 0) == 1
    if not need_stock_id and not spool_notnull:
        logger.debug("tray_mappings schema already up to date")
        return

    logger.info(
        "migrating tray_mappings (add stock_id=%s, relax spool_id=%s)",
        need_stock_id,
        spool_notnull,
    )

    legacy_table = "tray_mappings__legacy"
    if _table_exists(sync_conn, legacy_table):
        logger.warning("dropping leftover table %s from a previous failed migration", legacy_table)
        sync_conn.execute(text(f"DROP TABLE {legacy_table}"))

    for idx in (
        "ix_tray_mappings_printer_id_tray_id",
        "ix_tray_mappings_spool_id",
        "ux_tray_mappings_active_printer_tray",
    ):
        sync_conn.execute(text(f"DROP INDEX IF EXISTS {idx}"))

    sync_conn.execute(text(f"ALTER TABLE tray_mappings RENAME TO {legacy_table}"))

    # 按当前模型定义创建全新结构的表（含索引）
    from app.db.base import Base
    from app.db.models.tray_mapping import TrayMapping  # noqa: F401  确保模型已注册

    table = Base.metadata.tables["tray_mappings"]
    table.create(bind=sync_conn, checkfirst=False)

    sync_conn.execute(
        text(
            f"""
            INSERT INTO tray_mappings (id, printer_id, tray_id, stock_id, spool_id, bound_at, unbound_at)
            SELECT id, printer_id, tray_id, NULL, spool_id, bound_at, unbound_at
            FROM {legacy_table}
            """
        )
    )
    sync_conn.execute(text(f"DROP TABLE {legacy_table}"))
    logger.info("tray_mappings migrated to stock_id schema")


def ensure_printer_link_used(sync_conn: Connection) -> None:
    """老库补上 printers.link_used。新库由模型 create_all 建出该列。"""
    cols = _table_columns(sync_conn, "printers")
    if not cols or "link_used" in cols:
        return
    logger.info("adding printers.link_used")
    sync_conn.execute(text("ALTER TABLE printers ADD COLUMN link_used TEXT NOT NULL DEFAULT 'unknown'"))
