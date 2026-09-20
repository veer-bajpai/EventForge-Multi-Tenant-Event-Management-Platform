from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./eventforge.db"
    redis_url: str | None = None  # e.g. redis://localhost:6379/0 ; falls back to in-memory cache
    secret_key: str = "dev-secret-change-me-please-32-bytes-min"
    access_token_minutes: int = 15
    refresh_token_days: int = 14
    webhook_secret: str = "whsec_dev_secret"
    payment_mode: str = "demo"  # "demo" enables the simulated-confirmation endpoint
    cors_origins: str = "*"
    login_rate_limit: int = 10  # attempts per minute per (ip,email)
    public_cache_ttl: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
