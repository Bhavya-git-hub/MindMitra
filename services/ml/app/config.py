"""Typed settings for the AI service. Every secret comes from an environment variable."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "staging", "production"]
    # Shared with the API, which signs a short-lived token with it for every call.
    ml_service_token: SecretStr = Field(min_length=32)
    # "fake" answers from fixed sentences and sends nothing anywhere (development and tests).
    llm_provider: Literal["fake", "anthropic"] = "fake"
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-sonnet-5-5"
    anthropic_base_url: str = "https://api.anthropic.com"
    llm_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    llm_max_tokens: int = Field(default=400, ge=50, le=2000)
    # Trained wellness indicator models (python -m training.train writes them here).
    ml_model_dir: Path = Path(__file__).resolve().parent.parent / "models"

    @model_validator(mode="after")
    def _provider_is_usable(self) -> Self:
        if self.llm_provider == "anthropic" and not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
        if self.llm_provider == "fake" and self.app_env in ("staging", "production"):
            raise ValueError("LLM_PROVIDER=fake is for development and tests only")
        if not self.anthropic_base_url.startswith("https://") and self.app_env in (
            "staging",
            "production",
        ):
            raise ValueError("ANTHROPIC_BASE_URL must use https outside development")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
