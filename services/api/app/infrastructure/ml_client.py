"""Typed client for the internal AI service (``services/ml``).

Every call carries a fresh, five-minute service token signed with ``ML_SERVICE_TOKEN``. A slow
or failing service never blocks a student for long: calls time out, a connection error is
retried once, and after repeated failures a circuit breaker stops calling for a short while.
In every failure case the caller gets ``CompanionUnavailable`` and answers with a fixed reply;
crisis rules have already run in the API by then, so a failure never hides a crisis.

Nothing a student wrote is logged here: only the outcome and the status code.
"""

import dataclasses
import datetime as dt
import logging
import time
from collections.abc import Callable, Sequence
from typing import Any, Literal, Protocol

import httpx
import jwt

log = logging.getLogger("mindmitra.ml_client")

AUDIENCE = "mindmitra-ml"
ISSUER = "mindmitra-api"
TOKEN_LIFETIME = dt.timedelta(minutes=5)

ReplyKind = Literal["reply", "crisis", "redirect", "fallback", "unavailable"]


class CompanionUnavailable(Exception):
    """The AI service could not give an answer. Safe to log: holds no text."""


@dataclasses.dataclass(frozen=True)
class HistoryTurn:
    role: Literal["user", "assistant"]
    content: str


@dataclasses.dataclass(frozen=True)
class ServiceCrisis:
    action: Literal["none", "review", "escalate"]
    category: str | None
    severity: Literal["low", "moderate", "high", "imminent"] | None
    rules: tuple[str, ...]
    third_person: bool


@dataclasses.dataclass(frozen=True)
class CompanionReply:
    kind: ReplyKind
    reply: str | None
    crisis: ServiceCrisis
    topic: str
    flags: tuple[str, ...]
    model_version: str


class CompanionClient(Protocol):
    async def respond(self, message: str, history: Sequence[HistoryTurn]) -> CompanionReply: ...

    async def aclose(self) -> None: ...


def sign_service_token(secret: str, now: dt.datetime | None = None) -> str:
    issued = now or dt.datetime.now(dt.UTC)
    return jwt.encode(
        {"aud": AUDIENCE, "iss": ISSUER, "iat": issued, "exp": issued + TOKEN_LIFETIME},
        secret,
        algorithm="HS256",
    )


def _parse(data: dict[str, Any]) -> CompanionReply:
    c = data["crisis"]
    return CompanionReply(
        kind=data["kind"],
        reply=data.get("reply"),
        crisis=ServiceCrisis(
            action=c["action"],
            category=c.get("category"),
            severity=c.get("severity"),
            rules=tuple(c.get("rules", ())),
            third_person=bool(c.get("third_person", False)),
        ),
        topic=str(data.get("topic", "general")),
        flags=tuple(str(f) for f in data.get("flags", ())),
        model_version=str(data["model_version"])[:80],
    )


class CircuitBreaker:
    """Opens after ``threshold`` failures in a row; lets one call through after ``cooldown``."""

    def __init__(
        self,
        threshold: int = 3,
        cooldown_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.threshold = threshold
        self.cooldown = cooldown_seconds
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None

    def allow(self) -> bool:
        if self._opened_at is None:
            return True
        return self._clock() - self._opened_at >= self.cooldown

    def success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def failure(self) -> None:
        self._failures += 1
        if self._failures >= self.threshold:
            self._opened_at = self._clock()


class HttpCompanionClient:
    def __init__(
        self,
        base_url: str,
        secret: str,
        *,
        timeout_seconds: float = 25.0,
        transport: httpx.AsyncBaseTransport | None = None,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        self._secret = secret
        self._breaker = breaker or CircuitBreaker()
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds, connect=3.0),
            transport=transport,
        )

    async def respond(self, message: str, history: Sequence[HistoryTurn]) -> CompanionReply:
        if not self._breaker.allow():
            raise CompanionUnavailable("circuit open")
        body = {
            "message": message,
            "history": [{"role": t.role, "content": t.content} for t in history],
        }
        for attempt in (1, 2):
            headers = {"Authorization": f"Bearer {sign_service_token(self._secret)}"}
            try:
                r = await self._client.post(
                    "/internal/v1/companion/respond", json=body, headers=headers
                )
            except httpx.ConnectError as exc:
                if attempt == 1:  # the service may be restarting; nothing was processed
                    continue
                self._breaker.failure()
                log.warning("ml_client.unreachable")
                raise CompanionUnavailable("unreachable") from exc
            except httpx.HTTPError as exc:
                self._breaker.failure()
                log.warning("ml_client.error kind=%s", type(exc).__name__)
                raise CompanionUnavailable(type(exc).__name__) from exc
            if r.status_code != 200:
                self._breaker.failure()
                log.warning("ml_client.status code=%s", r.status_code)
                raise CompanionUnavailable(f"status {r.status_code}")
            try:
                reply = _parse(r.json())
            except (ValueError, KeyError, TypeError) as exc:
                self._breaker.failure()
                log.warning("ml_client.bad_response")
                raise CompanionUnavailable("bad response") from exc
            self._breaker.success()
            return reply
        raise CompanionUnavailable("unreachable")  # pragma: no cover - loop always returns

    async def aclose(self) -> None:
        await self._client.aclose()
