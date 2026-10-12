"""拓竹账号登录。回调按用户点登录时所在的页面跳回去。"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings
from app.core.crypto import decrypt_str, encrypt_str
from app.db.models.bambu_cloud_session import BambuCloudSession
from app.db.models.printer import Printer
from app.services.bambu_cloud import (
    describe_cloud_devices,
    exchange_ticket,
    expires_at_from,
    fetch_devices,
    fetch_profile,
    login_page_url,
    mqtt_username_from_token,
    pick_tokens,
    profile_uid_name,
)

router = APIRouter(prefix="/cloud", tags=["cloud"])

# 单进程内记住「从哪一页点的登录」。回调只认这里登记过的 state。
_PENDING: dict[str, dict] = {}


class LoginStart(BaseModel):
    region: str = Field(default="cn")
    return_path: str = "/settings/cloud"
    front_origin: str


class TicketBody(BaseModel):
    region: str = Field(default="cn")
    ticket: str = Field(min_length=1)


class AdoptBody(BaseModel):
    serial: str = Field(min_length=1)


def _region(value: str) -> str:
    return "cn" if value.strip().lower() in {"cn", "china", "中国"} else "global"


def _safe_return(path: str) -> str:
    path = (path or "/settings/cloud").strip() or "/settings/cloud"
    if not path.startswith("/") or path.startswith("//") or "\\" in path:
        return "/settings/cloud"
    return path


def _same_host(front_origin: str, request_host: str | None) -> str:
    parsed = urlparse(front_origin.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="前端地址无效")
    host = parsed.hostname.lower()
    req = (request_host or "").lower()
    allowed = {req, "localhost", "127.0.0.1"}
    if host not in allowed:
        raise HTTPException(status_code=400, detail="登录完成后只能回到本机页面")
    origin = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port:
        origin += f":{parsed.port}"
    return origin


def _html_redirect(url: str, text: str) -> HTMLResponse:
    safe = url.replace('"', "%22")
    body = f"""<!doctype html><meta charset="utf-8"><title>{text}</title>
<p>{text}</p><script>location.replace("{safe}")</script>"""
    return HTMLResponse(body)


async def _load_session(db: AsyncSession) -> BambuCloudSession | None:
    return (await db.execute(select(BambuCloudSession).order_by(BambuCloudSession.id.asc()).limit(1))).scalars().first()


async def _save_session(db: AsyncSession, *, region: str, access: str, refresh: str, expires_at: datetime, uid: str | None, username: str | None, name: str | None) -> BambuCloudSession:
    row = await _load_session(db)
    now = datetime.now(timezone.utc)
    if row is None:
        row = BambuCloudSession(id=1, region=region, access_token_enc="", refresh_token_enc="", updated_at=now)
        db.add(row)
    row.region = region
    row.access_token_enc = encrypt_str(settings.app_secret_key, access)
    row.refresh_token_enc = encrypt_str(settings.app_secret_key, refresh) if refresh else ""
    row.expires_at = expires_at
    row.uid = uid
    row.mqtt_username = username
    row.display_name = name
    row.updated_at = now
    await db.commit()
    await db.refresh(row)
    return row


async def _apply_ticket(db: AsyncSession, region: str, ticket: str) -> BambuCloudSession:
    raw = await exchange_ticket(region, ticket)
    access, refresh, expires_in = pick_tokens(raw)
    if not access:
        raise HTTPException(status_code=502, detail="拓竹没有返回访问令牌")
    profile = await fetch_profile(region, access)
    uid, name = profile_uid_name(profile)
    username = mqtt_username_from_token(access, uid)
    if not username:
        raise HTTPException(status_code=502, detail="无法从令牌识别云端用户")
    return await _save_session(
        db,
        region=region,
        access=access,
        refresh=refresh,
        expires_at=expires_at_from(access, expires_in),
        uid=uid,
        username=username,
        name=name,
    )


async def _access_token(row: BambuCloudSession) -> str:
    try:
        return decrypt_str(settings.app_secret_key, row.access_token_enc)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="云端令牌无法解密，请重新登录") from exc


@router.post("/login/start")
async def start_login(body: LoginStart, request: Request) -> dict:
    region = _region(body.region)
    origin = _same_host(body.front_origin, request.url.hostname)
    return_path = _safe_return(body.return_path)
    state = secrets.token_urlsafe(18)
    _PENDING[state] = {"region": region, "return_path": return_path, "front_origin": origin, "at": datetime.now(timezone.utc)}
    # 丢掉过期的登记，避免字典一直涨
    cutoff = datetime.now(timezone.utc).timestamp() - 600
    for key, item in list(_PENDING.items()):
        if item["at"].timestamp() < cutoff:
            _PENDING.pop(key, None)
    callback = str(request.base_url).rstrip("/") + f"/cloud/callback?state={quote(state, safe='')}"
    return {"login_url": login_page_url(region, callback), "return_path": return_path}


@router.get("/callback", response_class=HTMLResponse)
async def login_callback(
    request: Request,
    state: str = Query(default=""),
    ticket: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    pending = _PENDING.pop(state, None)
    if not pending:
        return _html_redirect("/", "登录状态已失效，请回到设置页重试")
    dest = pending["front_origin"] + pending["return_path"]
    if not ticket.strip():
        return _html_redirect(dest + "?cloud=error&message=" + quote("没有收到登录票据"), "没有收到登录票据")
    try:
        await _apply_ticket(db, pending["region"], ticket)
    except Exception as exc:
        message = str(getattr(exc, "detail", None) or exc)[:180]
        return _html_redirect(dest + "?cloud=error&message=" + quote(message), "登录失败")
    join = "&" if "?" in dest else "?"
    return _html_redirect(dest + join + "cloud=ok", "登录成功，正在返回")


@router.post("/ticket")
async def submit_ticket(body: TicketBody, db: AsyncSession = Depends(get_db)) -> dict:
    row = await _apply_ticket(db, _region(body.region), body.ticket)
    return {"ok": True, "display_name": row.display_name, "mqtt_username": row.mqtt_username}


@router.get("/session")
async def session_status(db: AsyncSession = Depends(get_db)) -> dict:
    row = await _load_session(db)
    if row is None:
        return {"logged_in": False}
    return {
        "logged_in": True,
        "region": row.region,
        "display_name": row.display_name,
        "mqtt_username": row.mqtt_username,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
    }


@router.delete("/session")
async def logout(db: AsyncSession = Depends(get_db)) -> dict:
    row = await _load_session(db)
    if row is not None:
        await db.delete(row)
        await db.commit()
    return {"ok": True}


@router.get("/devices")
async def cloud_devices(db: AsyncSession = Depends(get_db)) -> dict:
    row = await _load_session(db)
    if row is None:
        raise HTTPException(status_code=404, detail="尚未登录拓竹账号")
    token = await _access_token(row)
    try:
        devices = await fetch_devices(row.region, token)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"读取云端设备失败：{exc}") from exc
    printers = (await db.execute(select(Printer))).scalars().all()
    local = {p.serial.strip(): p for p in printers}
    return {"devices": describe_cloud_devices(devices, local)}


@router.post("/printers/adopt")
async def adopt_printer(body: AdoptBody, db: AsyncSession = Depends(get_db)) -> dict:
    """把云端账号下的一台机器并入本地。序列号已存在则直接返回那一行，不新建。"""
    row = await _load_session(db)
    if row is None:
        raise HTTPException(status_code=404, detail="尚未登录拓竹账号")
    serial = body.serial.strip()
    existing = (await db.execute(select(Printer).where(Printer.serial == serial))).scalars().first()
    token = await _access_token(row)
    devices = await fetch_devices(row.region, token)
    matched = next((d for d in devices if str(d.get("dev_id") or "").strip() == serial), None)
    if matched is None and existing is None:
        raise HTTPException(status_code=404, detail="这个序列号不在当前拓竹账号下")

    if existing is not None:
        changed = False
        code = str((matched or {}).get("dev_access_code") or "").strip()
        if code:
            current = ""
            try:
                current = decrypt_str(settings.app_secret_key, existing.lan_access_code_enc)
            except ValueError:
                current = ""
            if not current:
                existing.lan_access_code_enc = encrypt_str(settings.app_secret_key, code)
                changed = True
        if matched and not existing.alias and matched.get("name"):
            existing.alias = str(matched["name"])
            changed = True
        if matched and not existing.model:
            model = matched.get("dev_product_name") or matched.get("dev_model_name")
            if model:
                existing.model = str(model)
                changed = True
        if changed:
            existing.updated_at = datetime.now(timezone.utc)
            await db.commit()
        return {"printer_id": str(existing.id), "created": False, "same_printer": True}

    now = datetime.now(timezone.utc)
    code = str((matched or {}).get("dev_access_code") or "").strip()
    raw_model = (matched or {}).get("dev_product_name") or (matched or {}).get("dev_model_name")
    printer = Printer(
        ip="",
        serial=serial,
        alias=str(matched.get("name")) if matched and matched.get("name") else None,
        model=str(raw_model) if raw_model else None,
        lan_access_code_enc=encrypt_str(settings.app_secret_key, code),
        status="unknown",
        link_used="unknown",
        last_seen=None,
        created_at=now,
        updated_at=now,
    )
    db.add(printer)
    await db.commit()
    await db.refresh(printer)
    return {"printer_id": str(printer.id), "created": True, "same_printer": False}
