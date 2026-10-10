"""Providers and settings: the API key stays in the header, failures say nothing about what
was sent, and unsafe configurations refuse to start."""

import json

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.companion.context import Turn
from app.config import Settings
from app.providers.anthropic import AnthropicProvider
from app.providers.base import GenerationRequest, ProviderError
from app.providers.factory import build_provider
from app.providers.fake import FakeProvider

KEY = "sk-test-not-a-real-key-0000"
REQUEST = GenerationRequest(
    system="be kind", messages=(Turn("user", "PRIVATE-TEXT exams"),), max_tokens=200
)


def _provider(handler: httpx.MockTransport) -> AnthropicProvider:
    return AnthropicProvider(api_key=SecretStr(KEY), model="claude-test", transport=handler)


async def test_a_request_carries_the_key_in_the_header_and_the_prompt_in_the_body() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "  That sounds hard.  "}],
                "stop_reason": "end_turn",
            },
        )

    provider = _provider(httpx.MockTransport(handler))
    assert await provider.generate(REQUEST) == "That sounds hard."
    req = seen[0]
    assert req.url.path == "/v1/messages"
    assert req.headers["x-api-key"] == KEY
    assert req.headers["anthropic-version"]
    body = json.loads(req.content)
    assert body["model"] == "claude-test"
    assert body["system"] == "be kind"
    assert body["messages"] == [{"role": "user", "content": "PRIVATE-TEXT exams"}]
    assert KEY not in req.content.decode()
    await provider.aclose()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="PRIVATE-TEXT echoed back"),
        httpx.Response(429, json={"error": "rate limited"}),
        httpx.Response(200, json={"content": [], "stop_reason": "end_turn"}),
        httpx.Response(
            200, json={"content": [{"type": "text", "text": "x"}], "stop_reason": "refusal"}
        ),
        httpx.Response(200, text="not json"),
    ],
)
async def test_failures_raise_without_text_or_key(response: httpx.Response) -> None:
    provider = _provider(httpx.MockTransport(lambda _: response))
    with pytest.raises(ProviderError) as exc:
        await provider.generate(REQUEST)
    assert "PRIVATE-TEXT" not in str(exc.value)
    assert KEY not in str(exc.value)
    await provider.aclose()


async def test_a_timeout_is_a_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    provider = _provider(httpx.MockTransport(handler))
    with pytest.raises(ProviderError, match="timed out"):
        await provider.generate(REQUEST)
    await provider.aclose()


def _settings(**values: object) -> Settings:
    base: dict[str, object] = {"app_env": "test", "ml_service_token": "s" * 40}
    base.update(values)
    return Settings(**base)  # type: ignore[arg-type]


def test_the_default_provider_is_the_fake_one() -> None:
    assert isinstance(build_provider(_settings()), FakeProvider)


def test_anthropic_needs_a_key() -> None:
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY"):
        _settings(llm_provider="anthropic")
    provider = build_provider(_settings(llm_provider="anthropic", anthropic_api_key=KEY))
    assert isinstance(provider, AnthropicProvider)
    assert provider.model_id == "claude-sonnet-5-5"


@pytest.mark.parametrize("env", ["staging", "production"])
def test_the_fake_provider_is_refused_outside_development(env: str) -> None:
    with pytest.raises(ValidationError, match="development and tests only"):
        _settings(app_env=env)


def test_a_short_service_secret_is_refused() -> None:
    with pytest.raises(ValidationError):
        _settings(ml_service_token="short")


def test_the_key_never_appears_in_the_settings_repr() -> None:
    s = _settings(llm_provider="anthropic", anthropic_api_key=KEY)
    assert KEY not in repr(s) and KEY not in str(s.model_dump())
