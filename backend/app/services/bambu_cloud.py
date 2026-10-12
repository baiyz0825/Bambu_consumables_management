"""拓竹云账号：用官方登录页回调里的 ticket 换令牌，并按序列号对齐打印机。

社区（Bambu Studio / open-bambu-networking）的做法是：打开官方登录页，
回调带回 ticket，再 POST /v1/user-service/user/ticket/ 换成 accessToken。
云端 MQTT 与局域网订阅的是同一份 device/{serial}/report。
序列号相同的设备只对应 printers 表里的一行。
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

API_HOST = {
    "cn": "https://api.bambulab.cn",
    "global": "https://api.bambulab.com",
}
LOGIN_PAGE = {
    "cn": "https://bambulab.cn/zh/sign-in",
    "global": "https://bambulab.com/en/sign-in",
}
MQTT_HOST = {
    "cn": "cn.mqtt.bambulab.com",
    "global": "us.mqtt.bambulab.com",
}

_HEADERS = {
    "User-Agent": "bambu_network_agent/01.09.05.01",
    "X-BBL-Client-Name": "OrcaSlicer",
    "X-BBL-Client-Type": "slicer",
    "X-BBL-Client-Version": "01.09.05.51",
    "X-BBL-Language": "zh-CN",
    "Accept": "application/json",
    "Content-Type": "application/json",
}


def login_page_url(region: str, callback: str) -> str:
    base = LOGIN_PAGE["cn" if region == "cn" else "global"]
    return f"{base}?callback={quote(callback, safe='')}"


def api_host(region: str) -> str:
    return API_HOST["cn" if region == "cn" else "global"]


def mqtt_host(region: str) -> str:
    return MQTT_HOST["cn" if region == "cn" else "global"]


def jwt_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    raw = parts[1]
    raw += "=" * ((4 - len(raw) % 4) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(raw))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def mqtt_username_from_token(token: str, uid: str | None = None) -> str | None:
    payload = jwt_payload(token)
    name = payload.get("username") or payload.get("preferred_username")
    if isinstance(name, str) and name.startswith("u_"):
        return name
    if uid:
        text = str(uid)
        return text if text.startswith("u_") else f"u_{text}"
    return None


def expires_at_from(token: str, expires_in: object) -> datetime:
    payload = jwt_payload(token)
    exp = payload.get("exp")
    if isinstance(exp, (int, float)) and exp > 0:
        return datetime.fromtimestamp(float(exp), tz=timezone.utc)
    try:
        sec = int(expires_in) if expires_in is not None else 0
    except (TypeError, ValueError):
        sec = 0
    if sec > 10**11:
        return datetime.fromtimestamp(sec / 1000, tz=timezone.utc)
    if sec > 0:
        return datetime.now(timezone.utc) + timedelta(seconds=sec)
    return datetime.now(timezone.utc) + timedelta(days=30)


def unwrap_token_body(data: object) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    nested = data.get("data")
    if "accessToken" not in data and "token" not in data and isinstance(nested, dict):
        return nested
    return data


def pick_tokens(data: dict[str, Any]) -> tuple[str, str, object]:
    body = unwrap_token_body(data)
    access = body.get("accessToken") or body.get("token") or ""
    refresh = body.get("refreshToken") or body.get("refresh_token") or ""
    expires = body.get("expiresIn") if "expiresIn" in body else body.get("expires_in")
    return str(access or ""), str(refresh or ""), expires


def describe_cloud_devices(devices: list[dict], local_by_serial: dict[str, Any]) -> list[dict]:
    """云端设备按序列号对齐到已有打印机，不另起一行。"""
    out: list[dict] = []
    for dev in devices:
        if not isinstance(dev, dict):
            continue
        serial = str(dev.get("dev_id") or dev.get("serial") or "").strip()
        if not serial:
            continue
        local = local_by_serial.get(serial)
        out.append(
            {
                "serial": serial,
                "name": dev.get("name") or None,
                "model": dev.get("dev_product_name") or dev.get("dev_model_name") or None,
                "online": bool(dev.get("online")) if "online" in dev else None,
                "printer_id": str(local.id) if local is not None else None,
                "printer_alias": (local.alias or local.serial) if local is not None else None,
                "same_printer": local is not None,
            }
        )
    return out


def _auth_headers(token: str) -> dict[str, str]:
    headers = dict(_HEADERS)
    headers["Authorization"] = f"Bearer {token}"
    return headers


async def exchange_ticket(region: str, ticket: str) -> dict[str, Any]:
    host = api_host(region)
    ticket = ticket.strip()
    import httpx

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(f"{host}/v1/user-service/user/ticket/{ticket}", headers=_HEADERS, json={})
        if response.status_code in {404, 405}:
            response = await client.post(
                f"{host}/v1/user-service/user/ticket",
                headers=_HEADERS,
                json={"ticket": ticket},
            )
        response.raise_for_status()
        data = response.json()
    access, refresh, _expires = pick_tokens(data if isinstance(data, dict) else {})
    if not access:
        raise ValueError("拓竹没有返回访问令牌")
    return data if isinstance(data, dict) else {}


async def refresh_access_token(region: str, refresh_token: str) -> dict[str, Any]:
    import httpx

    host = api_host(region)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            f"{host}/v1/user-service/user/refreshtoken",
            headers=_HEADERS,
            json={"refreshToken": refresh_token},
        )
        response.raise_for_status()
        data = response.json()
    return data if isinstance(data, dict) else {}


async def fetch_profile(region: str, access_token: str) -> dict[str, Any]:
    import httpx

    host = api_host(region)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(f"{host}/v1/user-service/my/profile", headers=_auth_headers(access_token))
        if response.status_code >= 400:
            return {}
        data = response.json()
    return data if isinstance(data, dict) else {}


async def fetch_devices(region: str, access_token: str) -> list[dict]:
    import httpx

    host = api_host(region)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"{host}/v1/iot-service/api/user/bind",
            headers=_auth_headers(access_token),
        )
        response.raise_for_status()
        data = response.json()
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        devices = data.get("devices")
        if isinstance(devices, list):
            return [x for x in devices if isinstance(x, dict)]
    return []


def profile_uid_name(profile: dict[str, Any]) -> tuple[str | None, str | None]:
    body = profile.get("data") if isinstance(profile.get("data"), dict) else profile
    if not isinstance(body, dict):
        return None, None
    uid = body.get("uid") or body.get("uidStr") or body.get("user_id")
    name = body.get("name") or body.get("nickname") or body.get("account")
    return (str(uid) if uid else None, str(name) if name else None)
