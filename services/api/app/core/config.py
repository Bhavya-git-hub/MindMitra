"""Typed application settings. All secrets come from environment variables."""

from functools import lru_cache
from typing import Literal, Self
from urllib.parse import parse_qs, urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # No default: an unset APP_ENV must fail loudly rather than silently mean "development"
    # (which would, for example, allow seeding synthetic data).
    app_env: Literal["development", "test", "staging", "production"]

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

    @field_validator("field_encryption_key")
    @classmethod
    def _valid_key(cls, v: SecretStr) -> SecretStr:
        from app.core.crypto import _load_key  # fail at startup, not on first write

        try:
            _load_key(v.get_secret_value())
        except ValueError as exc:
            raise ValueError("FIELD_ENCRYPTION_KEY must be base64 of exactly 32 bytes") from exc
        return v

    @model_validator(mode="after")
    def _require_tls_outside_dev(self) -> Self:
        if self.app_env in ("staging", "production"):
            query = parse_qs(urlsplit(self.database_url.get_secret_value()).query)
            ssl = (query.get("ssl") or query.get("sslmode") or ["disable"])[0]
            if ssl not in ("require", "verify-ca", "verify-full", "true"):
                raise ValueError(
                    "DATABASE_URL must enable TLS (ssl=require or stronger) when APP_ENV is "
                    "staging or production"
                )
        return self

    @property
    def allows_seeding(self) -> bool:
        """Synthetic data may only ever be written to development and test databases."""
        return self.app_env in ("development", "test")

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
