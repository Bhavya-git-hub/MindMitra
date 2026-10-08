"""Typed application settings. All secrets come from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "staging", "production"] = "development"

    # Async SQLAlchemy URL, e.g. postgresql+asyncpg://user:pass@host:5432/db
    database_url: SecretStr
    db_pool_size: int = Field(default=10, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    db_pool_timeout_seconds: int = Field(default=30, ge=1)
    db_echo: bool = False

    # Base64-encoded 32-byte key for field-level encryption (AES-256-GCM).
    field_encryption_key: SecretStr

    @field_validator("database_url")
    @classmethod
    def _require_asyncpg(cls, v: SecretStr) -> SecretStr:
        if not v.get_secret_value().startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use the postgresql+asyncpg:// driver")
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
