"""HMS 错误码查询。

数据来自 ``app/data/hms_codes.json``（由 ``scripts/export_hms_codes.py`` 从
Bambu Studio 本地码表导出），因此运行环境无需安装 Studio。

关系链：

    MQTT print.hms[].{attr, code}
        → ecode = f"{attr:04X}{code:04X}"        （collector 已完成）
        → 本接口查 intro                          （故障文案）
        → ecode[:2] 定位模块                       （数字孪生部件红闪）
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Response

router = APIRouter(prefix="/hms", tags=["hms"])

_DATA_FILE = Path(__file__).resolve().parents[2] / "resources" / "hms_codes.json"

#: 单次查询上限，避免被当作全量遍历接口滥用
_MAX_LOOKUP = 200


@lru_cache(maxsize=1)
def _load() -> dict:
    """加载并缓存码表（进程内只读一次）。"""
    if not _DATA_FILE.is_file():
        return {
            "codes": {},
            "modules": {},
            "count": 0,
            "device": None,
            "device_name": None,
            "language": None,
        }
    return json.loads(_DATA_FILE.read_text(encoding="utf-8"))


@router.get("/meta")
def get_meta() -> dict:
    """码表元信息：机型、语言、条数、模块映射。"""
    data = _load()
    return {
        "device": data.get("device"),
        "device_name": data.get("device_name"),
        "language": data.get("language"),
        "count": data.get("count", 0),
        "modules": data.get("modules", {}),
        "generated_at": data.get("generated_at"),
    }


@router.get("/codes")
def list_codes(response: Response) -> dict:
    """全量码表（约 80KB）。前端可一次拉取后本地缓存。"""
    data = _load()
    response.headers["Cache-Control"] = "public, max-age=86400"
    return {"count": data.get("count", 0), "codes": data.get("codes", {})}


@router.get("/lookup")
def lookup(
    ecodes: str = Query(..., description="逗号分隔的 8 位 ecode，如 07038012,07058011"),
) -> dict:
    """按 ecode 批量查询故障文案与处理动作。"""
    wanted = [item.strip().upper() for item in ecodes.split(",") if item.strip()]
    if not wanted:
        raise HTTPException(status_code=400, detail="ecodes 不能为空")
    if len(wanted) > _MAX_LOOKUP:
        raise HTTPException(status_code=400, detail=f"单次最多查询 {_MAX_LOOKUP} 条")

    codes = _load().get("codes", {})
    found = {code: codes[code] for code in dict.fromkeys(wanted) if code in codes}
    missing = [code for code in dict.fromkeys(wanted) if code not in codes]
    return {"codes": found, "missing": missing}
