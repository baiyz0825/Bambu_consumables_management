"""应用配置（Pydantic BaseSettings）。

环境变量优先级高于默认值；生产部署时通过 ``DATABASE_URL`` 切换到 PostgreSQL。
默认 SQLite 单机模式（``sqlite+aiosqlite:///./data/consumables.db``），
数据目录 ``data/`` 相对于工作目录，``run_local.sh`` 会通过 ``.env.local``
覆盖为绝对路径以避免歧义。
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置项，支持环境变量覆盖。"""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    app_env: str = "dev"
    """运行环境标识（dev / prod），影响日志级别等。"""

    app_secret_key: str = "dev-secret-change-me"
    """Fernet 对称加密密钥，用于加密存储打印机的 LAN 访问码。
    **生产环境务必更换**，首次启动时 ``run_local.sh`` 会自动生成。
    """

    database_url: str = "sqlite+aiosqlite:///./data/consumables.db"
    """数据库连接串。SQLite 单机模式（默认）；PostgreSQL 部署时覆盖为
    ``postgresql+asyncpg://user:pass@host:5432/dbname``。
    """

    allow_insecure_mqtt_tls: bool = True
    """是否允许跳过 MQTT TLS 证书校验（拓竹局域网自签证书需开启）。"""

    material_ams_calibration_enabled: bool = False
    """是否启用 AMS 剩余量差值校准。默认关闭：RFID 剩余量精度不足，
    实际以切片 gcode 预估值 + 预扣/确认两阶段扣减为准。
    """


settings = Settings()
