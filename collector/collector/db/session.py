"""collector 数据库会话与引擎管理（SQLite / PostgreSQL 双方言支持）。

与 backend 共用同一个数据库：SQLite 模式下两端以 WAL + busy_timeout
协作并发读写；collector 的 ``init_db()`` 只建自身涉及的表
（printers / raw_events / normalized_events），其余表由 backend 补齐。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from collector.core.config import settings

logger = logging.getLogger(__name__)

#: SQLite 连接参数：写锁竞争时的等待上限（秒）。
SQLITE_BUSY_TIMEOUT_SEC: int = 15

#: 建表重试次数（应对 backend 恰好持有写锁的窗口）。
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

logger.info("collector database engine created (dialect=%s)", "sqlite" if _is_sqlite else "postgresql")


if _is_sqlite:

    @event.listens_for(engine.sync_engine, "connect")
    def _apply_sqlite_pragmas(dbapi_conn, _record) -> None:
        """每个新建连接应用并发安全 PRAGMA（与 backend/app/db/session.py 保持一致）。"""
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
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
    """SQLite 模式下幂等建表（仅 collector 涉及的表）；PG 模式为 no-op。"""
    if not _is_sqlite:
        logger.debug("init_db skipped (non-sqlite dialect, tables managed by alembic)")
        return

    from collector.db import models  # noqa: F401  触发模型注册到 Base.metadata
    from collector.db.base import Base

    for attempt in range(1, INIT_DB_MAX_ATTEMPTS + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("collector schema ensured (attempt=%d)", attempt)
            return
        except Exception:
            if attempt == INIT_DB_MAX_ATTEMPTS:
                logger.exception("init_db failed after %d attempts", attempt)
                raise
            logger.warning("init_db attempt %d failed, retrying...", attempt)
            await asyncio.sleep(1.0)


# ---------------------------------------------------------------------------
# 会话工具
# ---------------------------------------------------------------------------

async def get_session() -> AsyncIterator[AsyncSession]:
    """提供请求级数据库会话（自动关闭）。"""
    async with async_session_factory() as session:
        yield session
