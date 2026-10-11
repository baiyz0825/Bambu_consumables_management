"""跨方言列类型定义（SQLite / PostgreSQL 双支持）。

设计说明：
- 原项目 ORM 深度绑定 PG 专有类型（``postgresql.UUID`` / ``JSONB`` /
  ``DateTime(timezone=True)``），SQLite 模式下无法生成正确 DDL；
- 本模块以 SQLAlchemy ``TypeDecorator`` 装饰器模式抹平方言差异，
  对上层模型透明，符合开闭原则（新增方言只需扩展 ``load_dialect_impl``）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import BigInteger, DateTime, Integer, TypeDecorator
from sqlalchemy.engine import Dialect


class UTCDateTime(TypeDecorator[datetime]):
    """跨方言 UTC 时间戳。

    - PostgreSQL：渲染为 ``TIMESTAMP WITH TIME ZONE``（原生保留时区）；
    - SQLite：以 naive DATETIME 存储。写入时 aware -> naive(UTC) 规整，
      读出时补 ``timezone.utc``，保证 Python 层拿到的始终是 tz-aware，
      避免 event_processor 中 naive/aware 比较抛 TypeError。

    ``cache_ok=True`` 允许该类型参与 SQL 编译缓存。
    """

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> DateTime:
        """按方言选择底层实现（PG 保留时区，其余用普通 DATETIME）。"""
        if dialect.name == "postgresql":
            return dialect.type_descriptor(DateTime(timezone=True))
        return dialect.type_descriptor(DateTime())

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        """写库前规整：非 PG 方言下将 aware 时间转为 naive-UTC。"""
        if value is not None and value.tzinfo is not None and dialect.name != "postgresql":
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        """读库后规整：非 PG 方言下为 naive 时间补 UTC 时区。"""
        if value is not None and value.tzinfo is None and dialect.name != "postgresql":
            return value.replace(tzinfo=timezone.utc)
        return value


def sqlite_biginteger_pk() -> Any:
    """自增主键的跨方言列类型。

    SQLite 中仅 ``INTEGER PRIMARY KEY`` 会成为 rowid 别名（自增生效），
    ``BIGINT PRIMARY KEY`` 不会；因此 SQLite 渲染为 INTEGER，PG 保持 BIGINT。
    """
    return BigInteger().with_variant(Integer(), "sqlite")
