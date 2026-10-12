"""Typed client for the internal AI service (``services/ml``): the companion and the wellness
indicators.

Every call carries a fresh, five-minute service token signed with ``ML_SERVICE_TOKEN``. A slow
or failing service never blocks a student for long: calls time out, a connection error is
retried once, and after repeated failures a circuit breaker stops calling for a short while.
In every failure case the companion caller gets ``CompanionUnavailable`` and answers with a
fixed reply; crisis rules have already run in the API by then, so a failure never hides a
crisis. Indicator calls fail with ``IndicatorsUnavailable`` and have their own circuit breaker,
so missing indicator models never switch the companion off.

Nothing a student wrote is logged here: only the outcome and the status code.
"""

import dataclasses
import datetime as dt
import logging
import time
from collections.abc import Callable, Sequence
from typing import Any, Literal, Protocol, get_args

import httpx
import jwt

log = logging.getLogger("mindmitra.ml_client")

AUDIENCE = "mindmitra-ml"
ISSUER = "mindmitra-api"
TOKEN_LIFETIME = dt.timedelta(minutes=5)

ReplyKind = Literal["reply", "crisis", "redirect", "fallback", "unavailable"]
CrisisAction = Literal["none", "review", "escalate"]
Severity = Literal["low", "moderate", "high", "imminent"]


class MlUnavailable(Exception):
    """The AI service could not give an answer. Safe to log: holds no text."""


class CompanionUnavailable(MlUnavailable):
    pass


class IndicatorsUnavailable(MlUnavailable):
    pass


@dataclasses.dataclass(frozen=True)
class HistoryTurn:
    role: Literal["user", "assistant"]
    content: str


@dataclasses.dataclass(frozen=True)
class ServiceCrisis:
    action: CrisisAction
    category: str | None
    severity: Severity | None
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


@dataclasses.dataclass(frozen=True)
class DayRecord:
    """One day of a student's own check-ins, as the indicator models read them."""

    day: dt.date
    mood: int | None = None
    energy: int | None = None
    stress: int | None = None
    sleep_minutes: int | None = None
    sleep_quality: int | None = None
    bedtime_hour: float | None = None
    emotions: tuple[str, ...] = ()
    stressors: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class Indicator:
    indicator: str
    title: str
    meaning: str
    status: Literal["ok", "not_enough_data"]
    band: Literal["low", "moderate", "elevated"] | None
    level: str | None
    probabilities: dict[str, float]
    model_version: str


@dataclasses.dataclass(frozen=True)
class IndicatorReport:
    indicators: tuple[Indicator, ...]
    checkin_days: int
    notes_considered: int
    disclaimer: str


class IndicatorClient(Protocol):
    async def indicators(
        self, window_end: dt.date, days: Sequence[DayRecord], notes: Sequence[str]
    ) -> IndicatorReport: ...


def sign_service_token(secret: str, now: dt.datetime | None = None) -> str:
    issued = now or dt.datetime.now(dt.UTC)
    return jwt.encode(
        {"aud": AUDIENCE, "iss": ISSUER, "iat": issued, "exp": issued + TOKEN_LIFETIME},
        secret,
        algorithm="HS256",
    )


def _one_of(value: object, allowed: tuple[str, ...]) -> Any:
    """The service's answer drives the crisis path, so an unknown value is a bad response
    (which fails safe) rather than something to pass along."""
    if value not in allowed:
        raise ValueError("unexpected value")
    return value


def _parse(data: dict[str, Any]) -> CompanionReply:
    c = data["crisis"]
    severity = c.get("severity")
    return CompanionReply(
        kind=_one_of(data["kind"], get_args(ReplyKind)),
        reply=data.get("reply"),
        crisis=ServiceCrisis(
            action=_one_of(c["action"], get_args(CrisisAction)),
            category=c.get("category"),
            severity=None if severity is None else _one_of(severity, get_args(Severity)),
            rules=tuple(c.get("rules", ())),
            third_person=bool(c.get("third_person", False)),
        ),
        topic=str(data.get("topic", "general")),
        flags=tuple(str(f) for f in data.get("flags", ())),
        model_version=str(data["model_version"])[:80],
    )


def _day_json(d: DayRecord) -> dict[str, Any]:
    return {
        "day": d.day.isoformat(),
        "mood": d.mood,
        "energy": d.energy,
        "stress": d.stress,
        "sleep_minutes": d.sleep_minutes,
        "sleep_quality": d.sleep_quality,
        "bedtime_hour": d.bedtime_hour,
        "emotions": list(d.emotions),
        "stressors": list(d.stressors),
    }


def _parse_indicators(data: dict[str, Any]) -> IndicatorReport:
    return IndicatorReport(
        indicators=tuple(
            Indicator(
                indicator=str(i["indicator"]),
                title=str(i["title"]),
                meaning=str(i["meaning"]),
                status=i["status"],
                band=i.get("band"),
                level=i.get("level"),
                probabilities={str(k): float(v) for k, v in i.get("probabilities", {}).items()},
                model_version=str(i["model_version"])[:80],
            )
            for i in data["indicators"]
        ),
        checkin_days=int(data["checkin_days"]),
        notes_considered=int(data["notes_considered"]),
        disclaimer=str(data["disclaimer"]),
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
    """Implements both ``CompanionClient`` and ``IndicatorClient``."""

    def __init__(
        self,
        base_url: str,
        secret: str,
        *,
        timeout_seconds: float = 25.0,
        transport: httpx.AsyncBaseTransport | None = None,
        breaker: CircuitBreaker | None = None,
        indicator_breaker: CircuitBreaker | None = None,
    ) -> None:
        self._secret = secret
        self._breaker = breaker or CircuitBreaker()
        self._indicator_breaker = indicator_breaker or CircuitBreaker()
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds, connect=3.0),
            transport=transport,
        )

    async def _post(
        self,
        path: str,
        body: dict[str, Any],
        breaker: CircuitBreaker,
        error: type[MlUnavailable],
    ) -> dict[str, Any]:
        if not breaker.allow():
            raise error("circuit open")
        for attempt in (1, 2):
            headers = {"Authorization": f"Bearer {sign_service_token(self._secret)}"}
            try:
                r = await self._client.post(path, json=body, headers=headers)
            except httpx.ConnectError as exc:
                if attempt == 1:  # the service may be restarting; nothing was processed
                    continue
                breaker.failure()
                log.warning("ml_client.unreachable path=%s", path)
                raise error("unreachable") from exc
            except httpx.HTTPError as exc:
                breaker.failure()
                log.warning("ml_client.error path=%s kind=%s", path, type(exc).__name__)
                raise error(type(exc).__name__) from exc
            if r.status_code != 200:
                breaker.failure()
                log.warning("ml_client.status path=%s code=%s", path, r.status_code)
                raise error(f"status {r.status_code}")
            try:
                data = r.json()
                if not isinstance(data, dict):
                    raise TypeError("not an object")
            except (ValueError, TypeError) as exc:
                breaker.failure()
                log.warning("ml_client.bad_response path=%s", path)
                raise error("bad response") from exc
            return data
        raise error("unreachable")  # pragma: no cover - loop always returns

    async def respond(self, message: str, history: Sequence[HistoryTurn]) -> CompanionReply:
        body = {
            "message": message,
            "history": [{"role": t.role, "content": t.content} for t in history],
        }
        data = await self._post(
            "/internal/v1/companion/respond", body, self._breaker, CompanionUnavailable
        )
        try:
            reply = _parse(data)
        except (ValueError, KeyError, TypeError) as exc:
            self._breaker.failure()
            log.warning("ml_client.bad_response path=companion")
            raise CompanionUnavailable("bad response") from exc
        self._breaker.success()
        return reply

    async def indicators(
        self, window_end: dt.date, days: Sequence[DayRecord], notes: Sequence[str]
    ) -> IndicatorReport:
        body = {
            "window_end": window_end.isoformat(),
            "days": [_day_json(d) for d in days],
            "notes": list(notes),
        }
        breaker = self._indicator_breaker
        data = await self._post("/internal/v1/indicators", body, breaker, IndicatorsUnavailable)
        try:
            report = _parse_indicators(data)
        except (ValueError, KeyError, TypeError) as exc:
            breaker.failure()
            log.warning("ml_client.bad_response path=indicators")
            raise IndicatorsUnavailable("bad response") from exc
        breaker.success()
        return report

    async def aclose(self) -> None:
        await self._client.aclose()
