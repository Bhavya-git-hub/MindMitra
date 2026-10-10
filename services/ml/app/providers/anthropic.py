"""Claude through the Anthropic Messages API.

The API key comes from the ``ANTHROPIC_API_KEY`` environment variable and is only ever put in
the request header. Errors are reported by status code; the response body, which could echo
what was sent, is never logged or raised.
"""

from typing import Any, Final

import httpx
from pydantic import SecretStr

from app.providers.base import GenerationRequest, ProviderError

API_VERSION: Final = "2023-06-01"


class AnthropicProvider:
    def __init__(
        self,
        *,
        api_key: SecretStr,
        model: str,
        base_url: str = "https://api.anthropic.com",
        timeout_seconds: float = 20.0,
        temperature: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._model = model
        self._temperature = temperature
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_seconds, connect=5.0),
            headers={
                "x-api-key": api_key.get_secret_value(),
                "anthropic-version": API_VERSION,
                "content-type": "application/json",
            },
            transport=transport,
        )

    @property
    def model_id(self) -> str:
        return self._model

    async def generate(self, request: GenerationRequest) -> str:
        body: dict[str, Any] = {
            "model": self._model,
            "max_tokens": request.max_tokens,
            "temperature": self._temperature,
            "system": request.system,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        }
        try:
            response = await self._client.post("/v1/messages", json=body)
        except httpx.TimeoutException as exc:
            raise ProviderError("provider timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"provider unreachable ({type(exc).__name__})") from exc
        if response.status_code != 200:
            raise ProviderError(f"provider returned {response.status_code}")
        try:
            data = response.json()
            if data.get("stop_reason") == "refusal":
                raise ProviderError("provider refused")
            text = "".join(
                block.get("text", "")
                for block in data.get("content", [])
                if isinstance(block, dict) and block.get("type") == "text"
            )
        except (ValueError, AttributeError, TypeError) as exc:
            raise ProviderError("provider returned an unexpected response") from exc
        if not text.strip():
            raise ProviderError("provider returned no text")
        return text.strip()

    async def aclose(self) -> None:
        await self._client.aclose()
