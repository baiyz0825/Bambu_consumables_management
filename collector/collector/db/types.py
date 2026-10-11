"""跨方言列类型定义（SQLite / PostgreSQL 双支持）。

与 ``backend/app/db/types.py`` 保持同构：collector 与 backend 共享同一套
表结构（SQLite 模式下两端都可能执行 create_all），schema 必须完全对齐。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import BigInteger, DateTime, Integer, TypeDecorator
from sqlalchemy.engine import Dialect


class UTCDateTime(TypeDecorator[datetime]):
    """跨方言 UTC 时间戳（详见 backend/app/db/types.py 中的设计说明）。"""

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
    """自增主键的跨方言列类型（SQLite 渲染为 INTEGER 以成为 rowid 别名）。"""
    return BigInteger().with_variant(Integer(), "sqlite")
