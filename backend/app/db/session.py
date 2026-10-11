"""数据库会话与引擎管理（SQLite / PostgreSQL 双方言支持）。

职责：
- 依据 ``settings.database_url`` 构建异步引擎（aiosqlite / asyncpg）
- SQLite 模式：应用并发安全 PRAGMA（WAL / busy_timeout / foreign_keys）
- SQLite 模式：提供幂等的 ``init_db()`` 建表入口（PostgreSQL 走 alembic）
- 提供应用层 ``async_session_factory`` 与 FastAPI 依赖 ``get_session``
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

logger = logging.getLogger(__name__)

#: SQLite 连接参数：写锁竞争时的等待上限（秒）。
#: 与 collector 双进程共用同一库文件时，避免偶发 "database is locked" 立即失败。
SQLITE_BUSY_TIMEOUT_SEC: int = 15

#: init_db 建表的重试次数（应对另一进程恰好持有写锁的窗口）。
INIT_DB_MAX_ATTEMPTS: int = 10


def _is_sqlite_url(url: str) -> bool:
    """判断连接串是否指向 SQLite 方言。"""
    return url.startswith("sqlite")


_is_sqlite = _is_sqlite_url(settings.database_url)

# ---------------------------------------------------------------------------
# 引擎与会话工厂
# ---------------------------------------------------------------------------

_engine_kwargs: dict = {"pool_pre_ping": True}
if _is_sqlite:
    _engine_kwargs["connect_args"] = {"timeout": SQLITE_BUSY_TIMEOUT_SEC}

engine = create_async_engine(settings.database_url, **_engine_kwargs)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

logger.info("database engine created (dialect=%s)", "sqlite" if _is_sqlite else "postgresql")


if _is_sqlite:

    @event.listens_for(engine.sync_engine, "connect")
    def _apply_sqlite_pragmas(dbapi_conn, _record) -> None:
        """每个新建连接应用并发安全 PRAGMA。

        - ``journal_mode=WAL``：写时复制日志，读不阻塞写（backend 轮询事件表
          与 collector 持续写入并发的核心保障）；
        - ``busy_timeout``：写冲突时排队等待而非立即报错；
        - ``foreign_keys=ON``：SQLite 默认关闭外键，显式启用与 PG 行为对齐；
        - ``synchronous=NORMAL``：WAL 模式下的推荐持久化档位。
        """
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute(f"PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_SEC * 1000}")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()
        logger.debug("sqlite connection pragmas applied")


# ---------------------------------------------------------------------------
# 初始化（SQLite 建表）
# ---------------------------------------------------------------------------

async def init_db() -> None:
    """SQLite 模式下幂等建表；PostgreSQL 模式为 no-op（表由 alembic 迁移创建）。

    幂等性由 ``create_all(checkfirst=True)`` 保证，backend / collector 任一
    先启动都可安全调用。短暂写锁冲突按固定间隔重试。
    """
    if not _is_sqlite:
        logger.debug("init_db skipped (non-sqlite dialect, tables managed by alembic)")
        return

    from app.db import models  # noqa: F401  触发模型注册到 Base.metadata
    from app.db.base import Base
    from app.db.sqlite_migrate import ensure_tray_mapping_schema

    for attempt in range(1, INIT_DB_MAX_ATTEMPTS + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            # 老库结构补齐（create_all 不会改动已存在的表）。
            # 使用独立 AUTOCOMMIT 连接：建表 DDL 在 pysqlite 下会隐式提交，
            # 与 create_all 共事务会导致部分 DDL 落在事务外，行为不可控。
            async with engine.connect() as mconn:
                await mconn.execution_options(isolation_level="AUTOCOMMIT")
                await mconn.run_sync(ensure_tray_mapping_schema)
            logger.info("database schema ensured (attempt=%d)", attempt)
            return
        except Exception:
            if attempt == INIT_DB_MAX_ATTEMPTS:
                logger.exception("init_db failed after %d attempts", attempt)
                raise
            logger.warning("init_db attempt %d failed, retrying...", attempt)
            await asyncio.sleep(1.0)


# ---------------------------------------------------------------------------
# FastAPI 依赖
# ---------------------------------------------------------------------------

async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：提供请求级数据库会话（自动关闭）。"""
    async with async_session_factory() as session:
        yield session
