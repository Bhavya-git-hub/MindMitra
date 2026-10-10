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

    # --- authentication (SECURITY_ARCHITECTURE.md section 3) -----------------------------
    # Ed25519 private key that signs access JWTs: PEM, or base64 of the PEM.
    jwt_private_key: SecretStr
    jwt_issuer: str = "mindmitra-api"
    jwt_audience: str = "mindmitra"
    access_token_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    # Refresh tokens rotate on every use; an unused one expires after this idle period.
    refresh_token_ttl_seconds: int = Field(default=7 * 24 * 3600, ge=300)
    # Absolute session lifetime, whatever the activity (students vs staff).
    student_session_max_seconds: int = Field(default=30 * 24 * 3600, ge=3600)
    staff_session_max_seconds: int = Field(default=12 * 3600, ge=3600)
    password_reset_ttl_seconds: int = Field(default=30 * 60, ge=300, le=24 * 3600)
    account_setup_ttl_seconds: int = Field(default=72 * 3600, ge=3600)
    email_verification_ttl_seconds: int = Field(default=24 * 3600, ge=3600)
    login_lockout_threshold: int = Field(default=5, ge=3, le=20)
    # Per client IP, per minute, across the public auth endpoints (in-process limiter).
    auth_rate_limit_per_minute: int = Field(default=20, ge=1)
    # Comma-separated browser origins allowed by CORS (no wildcard).
    cors_origins: str = ""
    terms_policy_version: str = "2026-10-01"
    # Where e-mail notifications go. "none" records them as skipped; "log" writes one line per
    # delivery (ids only, never an address or text) for development.
    notification_email_provider: Literal["none", "log"] = "none"
    # Run reminders and notification delivery inside the API process. Off by default; a
    # deployment either turns it on or runs ``python -m app.workers.scheduler`` separately.
    scheduler_enabled: bool = False
    scheduler_interval_seconds: int = Field(default=60, ge=5, le=3600)
    # Open real-time connections allowed per user (tabs and devices).
    realtime_max_connections_per_user: int = Field(default=5, ge=1, le=50)

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

    @field_validator("jwt_private_key")
    @classmethod
    def _valid_jwt_key(cls, v: SecretStr) -> SecretStr:
        from app.core.access_tokens import load_private_key

        load_private_key(v.get_secret_value())  # raises ValueError with a clear message
        return v

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard_origin(cls, v: str) -> str:
        if "*" in v:
            raise ValueError("CORS_ORIGINS must list explicit origins (no wildcard)")
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
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

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
