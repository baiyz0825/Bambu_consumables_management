"""按日/周/月把消耗堆成颜色段，并用品牌单价估算成本。"""

from datetime import date, datetime, timedelta, timezone

from app.services.consumption_breakdown import build_consumption_breakdown


def _at(y: int, m: int, d: int, hh: int = 12) -> datetime:
    return datetime(y, m, d, hh, 0, tzinfo=timezone.utc)


def _row(**kwargs) -> dict:
    base = {
        "created_at": _at(2026, 10, 13),
        "grams": 100,
        "color": "红色",
        "color_hex": "#FF0000",
        "brand": "拓竹",
        "material": "PLA",
    }
    base.update(kwargs)
    return base


def test_day_week_month_keys():
    today = date(2026, 10, 13)
    assert today.weekday() == 1  # Tuesday

    day = build_consumption_breakdown(
        [], prices_by_brand={}, granularity="day", span=3, today=today
    )
    assert [b["key"] for b in day["buckets"]] == ["2026-10-11", "2026-10-12", "2026-10-13"]
    assert [b["label"] for b in day["buckets"]] == ["2026-10-11", "2026-10-12", "2026-10-13"]

    week = build_consumption_breakdown(
        [
            _row(created_at=_at(2026, 10, 11, 23), grams=30, color="黑色", color_hex="#000000"),
            _row(created_at=_at(2026, 10, 13, 1), grams=70),
        ],
        prices_by_brand={"拓竹": 80},
        granularity="week",
        span=2,
        today=today,
    )
    assert [b["key"] for b in week["buckets"]] == ["2026-10-05", "2026-10-12"]
    assert week["buckets"][0]["grams"] == 30
    assert week["buckets"][1]["grams"] == 70

    new_year = build_consumption_breakdown(
        [], prices_by_brand={}, granularity="week", span=1, today=date(2026, 1, 1)
    )
    assert new_year["buckets"][0]["key"] == "2025-12-29"

    month = build_consumption_breakdown(
        [
            _row(created_at=_at(2026, 9, 30), grams=5, color="白色", color_hex=None, brand="杂牌"),
            _row(created_at=_at(2026, 10, 1, 0), grams=9),
        ],
        prices_by_brand={"拓竹": 80},
        granularity="month",
        span=2,
        today=today,
    )
    assert [b["key"] for b in month["buckets"]] == ["2026-09", "2026-10"]
    assert month["buckets"][0]["grams"] == 5
    assert month["buckets"][1]["grams"] == 9

    year_turn = build_consumption_breakdown(
        [], prices_by_brand={}, granularity="month", span=3, today=date(2026, 1, 15)
    )
    assert [b["key"] for b in year_turn["buckets"]] == ["2025-11", "2025-12", "2026-01"]


def test_two_colors_stack_in_one_day():
    rows = [
        _row(grams=200, color="红色", color_hex="#FF0000"),
        _row(created_at=_at(2026, 10, 13, 18), grams=100, color="红色", color_hex="#FF0000"),
        _row(grams=50, color="蓝色", color_hex="#0000FF"),
    ]
    out = build_consumption_breakdown(
        rows, prices_by_brand={"拓竹": 80}, granularity="day", span=1, today=date(2026, 10, 13)
    )
    segments = out["buckets"][0]["segments"]
    assert len(segments) == 2
    assert segments[0]["color"] == "红色"
    assert segments[0]["color_hex"] == "#FF0000"
    assert segments[0]["grams"] == 300
    assert segments[0]["cost_est"] == 24.0
    assert segments[1]["color"] == "蓝色"
    assert segments[1]["grams"] == 50
    assert segments[1]["cost_est"] == 4.0
    assert out["buckets"][0]["grams"] == 350
    assert out["buckets"][0]["cost_est"] == 28.0


def test_priced_brand_and_missing_price():
    rows = [
        _row(grams=1000, brand="拓竹"),
        _row(grams=250, color="白色", color_hex=None, brand="未知", material="PETG"),
        _row(grams=100, color="灰色", color_hex="#888888", brand="零元", material="PLA"),
    ]
    out = build_consumption_breakdown(
        rows,
        prices_by_brand={"拓竹": 120, "零元": 0},
        granularity="day",
        span=1,
        today=date(2026, 10, 13),
    )
    assert out["totals"]["grams"] == 1350
    assert out["totals"]["cost_est"] == 120.0
    assert out["totals"]["unpriced_grams"] == 250
    by_brand = {s["brand"]: s for s in out["buckets"][0]["segments"]}
    assert by_brand["拓竹"]["cost_est"] == 120.0
    assert by_brand["未知"]["cost_est"] == 0.0
    assert by_brand["未知"]["color_hex"] is None
    assert by_brand["零元"]["cost_est"] == 0.0


def test_empty_buckets_stay_in_the_span():
    rows = [
        _row(created_at=_at(2026, 10, 10), grams=999),
        _row(created_at=_at(2026, 10, 11), grams=10, color="黑色", color_hex="#000000"),
    ]
    out = build_consumption_breakdown(
        rows, prices_by_brand={"拓竹": 100}, granularity="day", span=3, today=date(2026, 10, 13)
    )
    assert [b["key"] for b in out["buckets"]] == ["2026-10-11", "2026-10-12", "2026-10-13"]
    assert out["buckets"][0]["grams"] == 10
    assert out["buckets"][0]["segments"][0]["grams"] == 10
    assert out["buckets"][1]["grams"] == 0
    assert out["buckets"][1]["segments"] == []
    assert out["buckets"][1]["cost_est"] == 0
    assert out["buckets"][2]["grams"] == 0
    assert out["buckets"][2]["segments"] == []
    assert out["totals"]["grams"] == 10
    assert out["totals"]["unpriced_grams"] == 0
    monday = date(2026, 10, 13) - timedelta(days=date(2026, 10, 13).weekday())
    assert monday.isoformat() == "2026-10-12"


if __name__ == "__main__":
    test_day_week_month_keys()
    test_two_colors_stack_in_one_day()
    test_priced_brand_and_missing_price()
    test_empty_buckets_stay_in_the_span()
    print("ok")
