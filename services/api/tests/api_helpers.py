"""Helpers for calling the API in tests."""

from typing import Any

import httpx

from tests.api_world import Actor

API = "/api/v1"

# Signed-in access tokens for the shared cast, so the role matrix does not log in 100+ times.
# Tests that end a session (logout, deactivation, password change) use their own fresh users.
_tokens: dict[str, str] = {}


async def login(client: httpx.AsyncClient, email: str, password: str) -> httpx.Response:
    return await client.post(f"{API}/auth/login", json={"email": email, "password": password})


async def token_for(client: httpx.AsyncClient, actor: Actor, password: str) -> str:
    if actor.email not in _tokens:
        r = await login(client, actor.email, password)
        assert r.status_code == 200, r.text
        _tokens[actor.email] = r.json()["access_token"]
    return _tokens[actor.email]


async def auth_headers(client: httpx.AsyncClient, actor: Actor, password: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {await token_for(client, actor, password)}"}


async def call(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    token: str | None = None,
    json: Any = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    h = dict(headers or {})
    if token is not None:
        h["Authorization"] = f"Bearer {token}"
    return await client.request(method, f"{API}{path}", json=json, headers=h)
