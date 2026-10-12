"""读取已保存的拓竹云会话，并在临近过期时刷新访问令牌。"""

from __future__ import annotations

import base64
import json
import logging
import socket
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from sqlalchemy import select

from collector.core.config import settings
from collector.core.crypto import decrypt_str, encrypt_str
from collector.db.models.bambu_cloud_session import BambuCloudSession
from collector.db.session import async_session_factory

logger = logging.getLogger("collector")

API_HOST = {"cn": "https://api.bambulab.cn", "global": "https://api.bambulab.com"}
MQTT_HOST = {"cn": "cn.mqtt.bambulab.com", "global": "us.mqtt.bambulab.com"}
_HEADERS = {
    "User-Agent": "bambu_network_agent/01.09.05.01",
    "X-BBL-Client-Name": "OrcaSlicer",
    "X-BBL-Client-Type": "slicer",
    "Accept": "application/json",
    "Content-Type": "application/json",
}


@dataclass(frozen=True)
class CloudMqtt:
    region: str
    username: str
    token: str
    host: str
    fingerprint: str


def tcp_open(host: str, port: int, timeout: float = 2.0) -> bool:
    if not host:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _post_json(url: str, payload: dict) -> dict:
    req = urlrequest.Request(url, data=json.dumps(payload).encode("utf-8"), headers=_HEADERS, method="POST")
    context = ssl.create_default_context()
    with urlrequest.urlopen(req, timeout=20, context=context) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body if isinstance(body, dict) else {}


def _expires_at(token: str) -> datetime:
    try:
        part = token.split(".")[1]
        part += "=" * ((4 - len(part) % 4) % 4)
        payload = json.loads(base64.urlsafe_b64decode(part))
        exp = payload.get("exp") if isinstance(payload, dict) else None
        if isinstance(exp, (int, float)) and exp > 0:
            return datetime.fromtimestamp(float(exp), tz=timezone.utc)
    except Exception:
        pass
    return datetime.now(timezone.utc) + timedelta(days=30)


def _pick_access(data: dict) -> tuple[str, str]:
    body = data.get("data") if isinstance(data.get("data"), dict) and "accessToken" not in data and "token" not in data else data
    if not isinstance(body, dict):
        return "", ""
    access = str(body.get("accessToken") or body.get("token") or "")
    refresh = str(body.get("refreshToken") or body.get("refresh_token") or "")
    return access, refresh


async def load_cloud_mqtt() -> CloudMqtt | None:
    async with async_session_factory() as session:
        row = (await session.execute(select(BambuCloudSession).limit(1))).scalars().first()
        if row is None or not row.mqtt_username or not row.access_token_enc:
            return None
        try:
            token = decrypt_str(settings.app_secret_key, row.access_token_enc)
            refresh = decrypt_str(settings.app_secret_key, row.refresh_token_enc) if row.refresh_token_enc else ""
        except ValueError:
            logger.warning("cloud token cannot be decrypted")
            return None
        expires = _aware(row.expires_at)
        if refresh and expires is not None and expires < datetime.now(timezone.utc) + timedelta(days=1):
            try:
                host = API_HOST.get(row.region, API_HOST["global"])
                data = _post_json(f"{host}/v1/user-service/user/refreshtoken", {"refreshToken": refresh})
                access, new_refresh = _pick_access(data)
                if access:
                    token = access
                    row.access_token_enc = encrypt_str(settings.app_secret_key, access)
                    if new_refresh:
                        row.refresh_token_enc = encrypt_str(settings.app_secret_key, new_refresh)
                    row.expires_at = _expires_at(access)
                    row.updated_at = datetime.now(timezone.utc)
                    await session.commit()
                    logger.info("cloud access token refreshed")
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
                logger.warning("cloud token refresh failed; keeping the current token")
        return CloudMqtt(
            region=row.region,
            username=row.mqtt_username,
            token=token,
            host=MQTT_HOST.get(row.region, MQTT_HOST["global"]),
            fingerprint=token[-16:],
        )
