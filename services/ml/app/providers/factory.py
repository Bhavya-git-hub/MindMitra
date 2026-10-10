"""Builds the configured provider."""

from app.config import Settings
from app.providers.anthropic import AnthropicProvider
from app.providers.base import LLMProvider
from app.providers.fake import FakeProvider


def build_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "anthropic":
        assert settings.anthropic_api_key is not None  # checked by the settings
        return AnthropicProvider(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            base_url=settings.anthropic_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    return FakeProvider()
