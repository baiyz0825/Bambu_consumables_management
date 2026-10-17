"""从 raw_events 回补 normalized_events 的新增字段。

背景
----
``raw_events`` 保存了完整 MQTT payload，而 ``normalized_events`` 只保存当时
归一化出的字段子集。T0 新增了温度 / 层数 / 风扇 / 灯 / HMS 等字段后，
历史事件里没有这些键——本脚本用同一套归一化逻辑重算并回填。

两种模式
--------
- ``enrich``（默认，安全）：**只给已存在的事件补缺失字段**，不动 ``type``、
  不动已有值。适合已有业务数据、只想让孪生能看历史。
- ``fill``：额外为缺失的事件补插（``type`` 用当前逻辑重新推导）。会在历史
  区间产生新事件，仅建议在空库验证时使用。

用法
----
    python3 scripts/backfill_normalized.py --dry-run
    python3 scripts/backfill_normalized.py --limit 5000
    python3 scripts/backfill_normalized.py --printer <uuid> --mode fill

安全约束
--------
- ``--dry-run`` 只统计不写库；
- 单次 ``--limit`` 建议先小后大；
- 每 200 条提交一次，可随时中断。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

# 允许直接以脚本方式运行（无需 pip install -e）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from collector.db.models.normalized_event import NormalizedEvent  # noqa: E402
from collector.db.models.raw_event import RawEvent  # noqa: E402
from collector.db.session import async_session_factory  # noqa: E402
from collector.main import _event_id_for_payload, _normalize_event_from_payload  # noqa: E402

_BATCH = 200


def _merge_missing(existing: dict | None, fresh: dict) -> tuple[dict, int]:
    """只补 ``existing`` 里没有的键，返回 (合并结果, 新增键数)。"""
    merged = dict(existing or {})
    added = 0
    for key, value in fresh.items():
        if key not in merged:
            merged[key] = value
            added += 1
    return merged, added


async def run(args: argparse.Namespace) -> int:
    stats = {"scanned": 0, "no_print": 0, "updated": 0, "inserted": 0, "unchanged": 0, "fields": 0}

    async with async_session_factory() as session:
        stmt = select(RawEvent).order_by(RawEvent.printer_id, RawEvent.received_at)
        if args.printer:
            stmt = stmt.where(RawEvent.printer_id == uuid.UUID(args.printer))
        if args.limit:
            stmt = stmt.limit(args.limit)

        rows = (await session.execute(stmt)).scalars().all()

        for index, raw in enumerate(rows, start=1):
            stats["scanned"] += 1
            payload = raw.payload_json if isinstance(raw.payload_json, dict) else None
            normalized = _normalize_event_from_payload(payload) if payload else None
            if normalized is None:
                stats["no_print"] += 1
                continue

            event_id = _event_id_for_payload(raw.printer_id, raw.payload_hash)
            existing = (
                await session.execute(
                    select(NormalizedEvent).where(NormalizedEvent.event_id == event_id)
                )
            ).scalar_one_or_none()

            if existing is not None:
                merged, added = _merge_missing(existing.data_json, normalized)
                if added == 0:
                    stats["unchanged"] += 1
                else:
                    stats["updated"] += 1
                    stats["fields"] += added
                    if not args.dry_run:
                        existing.data_json = merged
            elif args.mode == "fill":
                stats["inserted"] += 1
                if not args.dry_run:
                    session.add(
                        NormalizedEvent(
                            event_id=event_id,
                            printer_id=raw.printer_id,
                            type="PrintProgress",
                            occurred_at=raw.received_at,
                            data_json=normalized,
                            raw_event_id=raw.id,
                        )
                    )
            else:
                stats["unchanged"] += 1

            if index % _BATCH == 0:
                if not args.dry_run:
                    await session.commit()
                print(f"  … {index}/{len(rows)}", flush=True)

        if not args.dry_run:
            await session.commit()

    print(
        "[%s] 扫描 %d | 无 print 字段 %d | 更新 %d（补 %d 个字段） | 新增 %d | 无需处理 %d"
        % (
            "dry-run" if args.dry_run else "done",
            stats["scanned"],
            stats["no_print"],
            stats["updated"],
            stats["fields"],
            stats["inserted"],
            stats["unchanged"],
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="回补 normalized_events 的新增字段")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写库")
    parser.add_argument("--limit", type=int, default=None, help="最多处理多少条 raw_events")
    parser.add_argument("--printer", default=None, help="只处理指定打印机 UUID")
    parser.add_argument("--mode", choices=("enrich", "fill"), default="enrich")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
