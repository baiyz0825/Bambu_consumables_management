from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.models.brand_price import BrandPrice


router = APIRouter(prefix="/brand-prices", tags=["brand-prices"])


class BrandPriceUpsert(BaseModel):
    price_per_kg: float = Field(..., ge=0)


def _out(row: BrandPrice) -> dict:
    return {
        "brand": row.brand,
        "price_per_kg": float(row.price_per_kg),
        "updated_at": row.updated_at,
    }


def _brand_or_400(brand: str) -> str:
    cleaned = (brand or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="brand is empty")
    return cleaned


@router.get("")
async def list_brand_prices(db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (await db.execute(select(BrandPrice).order_by(BrandPrice.brand.asc()))).scalars().all()
    return [_out(row) for row in rows]


@router.put("/{brand}")
async def upsert_brand_price(
    brand: str,
    body: BrandPriceUpsert,
    db: AsyncSession = Depends(get_db),
) -> dict:
    brand = _brand_or_400(brand)
    now = datetime.now(timezone.utc)
    row = await db.get(BrandPrice, brand)
    if row is None:
        row = BrandPrice(brand=brand, price_per_kg=body.price_per_kg, updated_at=now)
        db.add(row)
    else:
        row.price_per_kg = body.price_per_kg
        row.updated_at = now
    await db.commit()
    await db.refresh(row)
    return _out(row)


@router.delete("/{brand}", status_code=204)
async def delete_brand_price(brand: str, db: AsyncSession = Depends(get_db)) -> None:
    brand = _brand_or_400(brand)
    row = await db.get(BrandPrice, brand)
    if row is None:
        raise HTTPException(status_code=404, detail="brand price not found")
    await db.delete(row)
    await db.commit()
