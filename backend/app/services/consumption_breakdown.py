"""把消耗行分到日/周/月桶里，并按颜色堆叠。不访问数据库。"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP


def _utc_day(dt: datetime) -> date:
    try:
        return dt.astimezone(timezone.utc).date()
    except Exception:
        return dt.date()


def estimate_cost(grams: int, price_per_kg: float | Decimal | None) -> float:
    """元。没有品牌单价时为 0。有单价时按 grams/1000 * price_per_kg。"""
    if price_per_kg is None:
        return 0.0
    amount = (Decimal(int(grams)) * Decimal(str(price_per_kg)) / Decimal(1000)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return float(amount)


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def bucket_key(day: date, granularity: str) -> str:
    if granularity == "day":
        return day.isoformat()
    if granularity == "week":
        monday = day - timedelta(days=day.weekday())
        return monday.isoformat()
    if granularity == "month":
        return f"{day.year:04d}-{day.month:02d}"
    raise ValueError(f"unsupported granularity: {granularity}")


def bucket_keys(today: date, granularity: str, span: int) -> list[str]:
    """span 个桶，最后一桶包含 today。周键是周一，月键是 YYYY-MM。"""
    if granularity not in ("day", "week", "month"):
        raise ValueError(f"unsupported granularity: {granularity}")
    if span < 1:
        raise ValueError("span must be >= 1")

    if granularity == "day":
        start = today - timedelta(days=span - 1)
        return [(start + timedelta(days=i)).isoformat() for i in range(span)]

    if granularity == "week":
        this_monday = today - timedelta(days=today.weekday())
        start_monday = this_monday - timedelta(weeks=span - 1)
        return [(start_monday + timedelta(weeks=i)).isoformat() for i in range(span)]

    year, month = _shift_month(today.year, today.month, -(span - 1))
    keys: list[str] = []
    for _ in range(span):
        keys.append(f"{year:04d}-{month:02d}")
        year, month = _shift_month(year, month, 1)
    return keys


def breakdown_range(today: date, granularity: str, span: int) -> tuple[date, date, list[str]]:
    """返回 (起始日含, 结束日不含, 桶键)。结束日是 today 的下一天。"""
    keys = bucket_keys(today, granularity, span)
    if granularity == "month":
        year, month = int(keys[0][:4]), int(keys[0][5:7])
        start = date(year, month, 1)
    else:
        start = date.fromisoformat(keys[0])
    return start, today + timedelta(days=1), keys


def build_consumption_breakdown(
    rows: list[dict],
    *,
    prices_by_brand: dict[str, float | Decimal],
    granularity: str,
    span: int,
    today: date,
) -> dict:
    """
    rows: created_at, grams, color, color_hex, brand, material.
    窗口外的行忽略。同一桶内按 (color, color_hex, brand, material) 合并。
    品牌没有单价时，该段 cost_est 为 0，克数计入 unpriced_grams。
    """
    keys = bucket_keys(today, granularity, span)
    allowed = set(keys)
    stacked: dict[str, dict[tuple, int]] = {key: {} for key in keys}

    for row in rows:
        grams = int(row.get("grams") or 0)
        if grams <= 0:
            continue
        created_at = row.get("created_at")
        if not isinstance(created_at, datetime):
            continue
        key = bucket_key(_utc_day(created_at), granularity)
        if key not in allowed:
            continue
        seg_key = (
            row.get("color"),
            row.get("color_hex"),
            row.get("brand"),
            row.get("material"),
        )
        bucket = stacked[key]
        bucket[seg_key] = bucket.get(seg_key, 0) + grams

    buckets: list[dict] = []
    total_grams = 0
    total_cost = Decimal("0")
    unpriced_grams = 0

    for key in keys:
        segments: list[dict] = []
        bucket_grams = 0
        bucket_cost = Decimal("0")
        for (color, color_hex, brand, material), grams in stacked[key].items():
            price = None if brand not in prices_by_brand else prices_by_brand[brand]
            if price is None:
                cost = 0.0
                unpriced_grams += grams
            else:
                cost = estimate_cost(grams, price)
            segments.append(
                {
                    "color": color,
                    "color_hex": color_hex,
                    "brand": brand,
                    "material": material,
                    "grams": grams,
                    "cost_est": cost,
                }
            )
            bucket_grams += grams
            bucket_cost += Decimal(str(cost))
        segments.sort(
            key=lambda s: (
                -int(s["grams"]),
                str(s["color"] or ""),
                str(s["brand"] or ""),
                str(s["material"] or ""),
                str(s["color_hex"] or ""),
            )
        )
        buckets.append(
            {
                "key": key,
                "label": key,
                "grams": bucket_grams,
                "cost_est": float(bucket_cost),
                "segments": segments,
            }
        )
        total_grams += bucket_grams
        total_cost += bucket_cost

    return {
        "granularity": granularity,
        "span": span,
        "totals": {
            "grams": total_grams,
            "cost_est": float(total_cost),
            "unpriced_grams": unpriced_grams,
        },
        "buckets": buckets,
    }
