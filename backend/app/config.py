"""Налаштування застосунку (змінні середовища)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./wms.db"
    jwt_secret: str = "change-me-in-production-wms-secret-key"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    # Зовнішні системи (mock-сервіси за замовчуванням живуть у самому API, /mock/...)
    erp_url: str = "http://localhost:8000/mock/erp"
    delivery_url: str = "http://localhost:8000/mock/delivery"
    http_timeout: float = 5.0

    worker_interval: float = 2.0
    max_event_attempts: int = 20

    gs1_company_prefix: str = "4820000"
    cors_origins: str = "*"
    warehouse_code: str = "WH1"


settings = Settings()
