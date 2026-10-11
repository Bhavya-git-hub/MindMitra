"""Regression tests from the authentication and configuration security review of the AI
service: configuration errors never echo a secret, and the service token is refused in every
shape other than the one the API makes."""

import base64
import datetime as dt
import json
from collections.abc import Callable
from typing import Any

import httpx
import jwt
import pytest
from pydantic import ValidationError

from app.auth import AUDIENCE, ISSUER, sign_service_token
from app.config import Settings
from app.providers.base import LLMProvider

Client = Callable[[LLMProvider | None], httpx.AsyncClient]
URL = "/internal/v1/companion/respond"
SECRET = "SUPERSECRET-must-not-be-echoed"  # noqa: S105 - a marker, not a credential


@pytest.mark.parametrize(
    "values",
    [
        pytest.param({"ml_service_token": SECRET[:20]}, id="short-service-token"),
        pytest.param(
            {
                "ml_service_token": SECRET * 2,
                "llm_provider": "anthropic",
                "anthropic_api_key": SECRET,
                "anthropic_base_url": "http://plain.example",
            },
            id="insecure-model-url",
        ),
    ],
)
def test_settings_errors_never_echo_secret_values(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, app_env="production", **values)  # type: ignore[call-arg]
    # str() is what a crashing process prints into the deployment logs.
    assert "SUPERSECRET" not in str(caught.value)


def _b64(data: dict[str, object]) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def _bad_tokens(secret: str) -> dict[str, str]:
    now = dt.datetime.now(dt.UTC)
    good = {"aud": AUDIENCE, "iss": ISSUER, "iat": now, "exp": now + dt.timedelta(minutes=5)}
    later = now + dt.timedelta(days=30)
    payload = sign_service_token(secret).split(".")[1]
    return {
        "alg none": f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{payload}.",
        "no exp": jwt.encode({k: v for k, v in good.items() if k != "exp"}, secret, "HS256"),
        "no iat": jwt.encode({k: v for k, v in good.items() if k != "iat"}, secret, "HS256"),
        "issued in the future": jwt.encode(
            dict(good, iat=later, exp=later + dt.timedelta(minutes=5)), secret, "HS256"
        ),
        "HS512 with the right secret": jwt.encode(good, secret, "HS512"),
        "another secret": jwt.encode(good, secret[::-1], "HS256"),
    }


@pytest.mark.filterwarnings("ignore:The HMAC key is .* below the minimum")
async def test_service_token_shapes_are_refused(make_client: Client, settings: Settings) -> None:
    client = make_client(None)
    for label, token in _bad_tokens(settings.ml_service_token.get_secret_value()).items():
        for path, method in ((URL, "POST"), ("/internal/v1/models", "GET")):
            r = await client.request(
                method,
                path,
                json={"message": "hi"} if method == "POST" else None,
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 401, (label, path)
