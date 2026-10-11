from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, model_validator

from app.schemas.common import APIModel


class TrayMappingCreate(BaseModel):
    """托盘绑定创建。

    stock_id 和 spool_id 二选一（推荐 stock_id）。两者都为空将报错。
    """

    printer_id: UUID
    tray_id: int
    stock_id: UUID | None = None
    spool_id: UUID | None = None

    @model_validator(mode="after")
    def _validate_target(self) -> "TrayMappingCreate":
        if self.stock_id is None and self.spool_id is None:
            raise ValueError("stock_id 或 spool_id 至少提供一个")
        return self


class TrayMappingOut(APIModel):
    id: int
    printer_id: UUID
    tray_id: int
    stock_id: UUID | None = None
    spool_id: UUID | None = None
    bound_at: datetime
    unbound_at: datetime | None

    # 关联的 MaterialStock 摘要（list 接口填充，方便前端直接展示）
    stock_material: str | None = None
    stock_color: str | None = None
    stock_brand: str | None = None
    stock_remaining_grams: int | None = None


class TrayMappingUnbind(BaseModel):
    printer_id: UUID
    tray_id: int
