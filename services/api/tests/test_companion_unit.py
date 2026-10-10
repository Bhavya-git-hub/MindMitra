"""Unit tests for the companion's building blocks in the API: the embedded crisis rules (and
that they match the AI service's copy), the AI service client, and its settings."""

import datetime as dt
import json
import logging
from pathlib import Path

import httpx
import jwt
import pytest
from pydantic import ValidationError

from app.application.companion import crisis_reply
from app.core.config import Settings
from app.domain.safety import crisis_rules
from app.domain.wellness.support_prompt import show_support_prompt
from app.infrastructure.ml_client import (
    AUDIENCE,
    ISSUER,
    CircuitBreaker,
    CompanionUnavailable,
    DayRecord,
    HistoryTurn,
    HttpCompanionClient,
    IndicatorsUnavailable,
)

API_COPY = Path(crisis_rules.__file__).parent
ML_COPY = Path(__file__).resolve().parents[2] / "ml" / "safety"
SECRET = "s" * 40
OK_BODY = {
    "kind": "reply",
    "reply": "That sounds hard.",
    "crisis": {
        "action": "none",
        "category": None,
        "severity": None,
        "rules": [],
        "third_person": False,
        "requires_human": False,
    },
    "topic": "academic_stress",
    "flags": [],
    "model_version": "fake-companion-1|companion-prompt-x|crisis-rules-x",
    "disclaimer": "…",
}


# ---- the embedded crisis rules --------------------------------------------------------------


@pytest.mark.parametrize("name", ["crisis_rules.py", "crisis_lexicon.json"])
def test_the_api_copy_of_the_crisis_rules_matches_the_ai_service(name: str) -> None:
    if not (ML_COPY / name).exists():
        pytest.skip("services/ml is not checked out next to services/api")
    assert (API_COPY / name).read_bytes() == (ML_COPY / name).read_bytes(), (
        f"copy services/ml/safety/{name} to app/domain/safety/{name}"
    )


@pytest.mark.parametrize(
    "text",
    [
        "I want to kill myself",
        "i dont want to live anymore",
        "I started cutting again",
        "my uncle hits me",
        "I need help right now",
        "मैं आत्महत्या करना चाहता हूँ",
    ],
)
def test_the_embedded_rules_catch_a_crisis(text: str) -> None:
    assert crisis_rules.detect(text).crisis


@pytest.mark.parametrize("text", ["this exam is killing me", "I need help with my essay now"])
def test_the_embedded_rules_leave_everyday_words_alone(text: str) -> None:
    assert not crisis_rules.detect(text).show_resources


def test_check_in_support_prompt_uses_the_rules() -> None:
    # A gentle-tier phrase the old phrase list did not know.
    assert show_support_prompt(mood_score=3, stress_level=None, note="I feel so hopeless")
    assert not show_support_prompt(mood_score=3, stress_level=None, note="good day")


def test_the_lexicon_is_valid_json_with_a_version() -> None:
    raw = json.loads((API_COPY / "crisis_lexicon.json").read_text(encoding="utf-8"))
    assert raw["version"] == crisis_rules.rules_version()


@pytest.mark.parametrize(
    ("category", "told", "already", "expect"),
    [
        ("suicidal_ideation", True, False, "let your counsellor know"),
        ("self_harm", False, False, "counselling team know"),
        ("abuse_or_unsafe_situation", True, False, "not your fault"),
        ("harm_to_others", False, False, "step away"),
        ("acute_distress", True, True, "already knows"),
    ],
)
def test_crisis_replies(category: str, told: bool, already: bool, expect: str) -> None:
    text = crisis_reply(category, told_care_team=told, already_open=already)
    assert expect in text
    assert "emergency number" in text
    assert "diagnos" not in text.lower()


# ---- the AI service client ------------------------------------------------------------------


async def test_every_call_carries_a_short_lived_service_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=OK_BODY)

    client = HttpCompanionClient("http://ml", SECRET, transport=httpx.MockTransport(handler))
    reply = await client.respond("exams", [HistoryTurn("user", "hi")])
    assert reply.kind == "reply" and reply.topic == "academic_stress"
    token = seen[0].headers["Authorization"].removeprefix("Bearer ")
    claims = jwt.decode(token, SECRET, algorithms=["HS256"], audience=AUDIENCE, issuer=ISSUER)
    assert claims["exp"] - claims["iat"] <= 300
    body = json.loads(seen[0].content)
    assert body == {"message": "exams", "history": [{"role": "user", "content": "hi"}]}
    await client.aclose()


async def test_a_connection_error_is_retried_once() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json=OK_BODY)

    client = HttpCompanionClient("http://ml", SECRET, transport=httpx.MockTransport(handler))
    assert (await client.respond("hi", [])).kind == "reply"
    assert calls == 2
    await client.aclose()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="PRIVATE"),
        httpx.Response(401, json={"detail": "unauthorized"}),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"kind": "reply"}),
    ],
)
async def test_failures_become_unavailable_without_text_in_logs(
    response: httpx.Response, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    client = HttpCompanionClient(
        "http://ml", SECRET, transport=httpx.MockTransport(lambda _: response)
    )
    with pytest.raises(CompanionUnavailable):
        await client.respond("PRIVATE-WORDS", [])
    assert "PRIVATE" not in caplog.text
    await client.aclose()


async def test_a_timeout_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    client = HttpCompanionClient("http://ml", SECRET, transport=httpx.MockTransport(handler))
    with pytest.raises(CompanionUnavailable):
        await client.respond("hi", [])
    await client.aclose()


async def test_the_circuit_opens_after_repeated_failures_and_recovers() -> None:
    now = [0.0]
    breaker = CircuitBreaker(threshold=3, cooldown_seconds=30, clock=lambda: now[0])
    calls = 0
    status = [500]

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status[0], json=OK_BODY)

    client = HttpCompanionClient(
        "http://ml", SECRET, transport=httpx.MockTransport(handler), breaker=breaker
    )
    for _ in range(3):
        with pytest.raises(CompanionUnavailable):
            await client.respond("hi", [])
    with pytest.raises(CompanionUnavailable, match="circuit open"):
        await client.respond("hi", [])
    assert calls == 3  # the open circuit did not call
    now[0] = 31.0
    status[0] = 200
    assert (await client.respond("hi", [])).kind == "reply"
    assert breaker.allow()
    await client.aclose()


# ---- settings -------------------------------------------------------------------------------


def _settings(**values: object) -> Settings:
    from app.core.config import get_settings

    base = get_settings().model_dump()
    base.update(values)
    return Settings(**base)


def test_an_ai_service_url_needs_a_long_enough_secret() -> None:
    with pytest.raises(ValidationError, match="ML_SERVICE_TOKEN"):
        _settings(ml_service_url="http://ml:8001", ml_service_token=None)
    with pytest.raises(ValidationError, match="ML_SERVICE_TOKEN"):
        _settings(ml_service_url="http://ml:8001", ml_service_token="short")
    ok = _settings(ml_service_url="http://ml:8001", ml_service_token=SECRET)
    assert ok.ml_service_url == "http://ml:8001"
    assert SECRET not in repr(ok)


def test_the_token_lifetime_is_five_minutes() -> None:
    from app.infrastructure.ml_client import sign_service_token

    now = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    claims = jwt.decode(
        sign_service_token(SECRET, now),
        SECRET,
        algorithms=["HS256"],
        audience=AUDIENCE,
        issuer=ISSUER,
        options={"verify_exp": False},
    )
    assert claims["exp"] - claims["iat"] == 300


# ---- wellness indicators through the same client ---------------------------------------------

INDICATORS_BODY = {
    "indicators": [
        {
            "indicator": "stress_level",
            "title": "Stress level",
            "meaning": "How much pressure your check-ins suggest.",
            "status": "ok",
            "band": "moderate",
            "level": "moderate",
            "probabilities": {"low": 0.2, "moderate": 0.5, "high": 0.3},
            "model_version": "stress_level-xgboost-20261010-abcd1234",
        }
    ],
    "checkin_days": 9,
    "notes_considered": 1,
    "disclaimer": "Not a diagnosis.",
}


async def test_indicators_send_days_and_notes_and_parse_the_report() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=INDICATORS_BODY)

    client = HttpCompanionClient("http://ml", SECRET, transport=httpx.MockTransport(handler))
    day = DayRecord(dt.date(2026, 10, 1), mood=2, bedtime_hour=23.5, emotions=("tired",))
    report = await client.indicators(dt.date(2026, 10, 10), [day], ["a note"])
    assert seen[0].url.path == "/internal/v1/indicators"
    assert seen[0].headers["Authorization"].startswith("Bearer ")
    assert json.loads(seen[0].content) == {
        "window_end": "2026-10-10",
        "days": [
            {
                "day": "2026-10-01",
                "mood": 2,
                "energy": None,
                "stress": None,
                "sleep_minutes": None,
                "sleep_quality": None,
                "bedtime_hour": 23.5,
                "emotions": ["tired"],
                "stressors": [],
            }
        ],
        "notes": ["a note"],
    }
    assert report.checkin_days == 9 and report.indicators[0].band == "moderate"
    await client.aclose()


async def test_missing_indicator_models_never_open_the_companion_circuit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/internal/v1/indicators":
            return httpx.Response(503, json={"detail": "indicator models unavailable"})
        return httpx.Response(200, json=OK_BODY)

    client = HttpCompanionClient("http://ml", SECRET, transport=httpx.MockTransport(handler))
    for _ in range(5):
        with pytest.raises(IndicatorsUnavailable):
            await client.indicators(dt.date(2026, 10, 10), [], ["PRIVATE-NOTE"])
    assert (await client.respond("hi", [])).kind == "reply"
    assert "PRIVATE" not in caplog.text
    await client.aclose()
