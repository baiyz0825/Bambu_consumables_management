"""采集器配置（Pydantic BaseSettings）。

与 backend 共享数据库，连接串默认值和切换逻辑一致。
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """采集器全局配置项，支持环境变量覆盖。"""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    app_env: str = "dev"
    """运行环境标识。"""

    app_secret_key: str = "dev-secret-change-me"
    """Fernet 密钥（与 backend 相同），用于解密打印机的 LAN 访问码。"""

    database_url: str = "sqlite+aiosqlite:///./data/consumables.db"
    """数据库连接串，默认 SQLite 单机模式。"""

    allow_insecure_mqtt_tls: bool = True
    """是否允许跳过 MQTT TLS 证书校验。"""


settings = Settings()
