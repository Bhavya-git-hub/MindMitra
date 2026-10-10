"""AI wellness indicators through the API: what is sent to the AI service, who may see the
result (the student, and a care-team therapist only with the AI-signals consent), what the
therapist's view leaves out, and the answer when the service is missing or down.

The AI service is replaced by ``FakeIndicators``; the models have their own tests
(``services/ml/tests``).
"""

import datetime as dt
from collections.abc import AsyncIterator, Sequence
from decimal import Decimal
from typing import Literal

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.api.main import create_app
from app.api.rate_limit import SlidingWindowRateLimiter
from app.application.auth.delivery import InMemoryTokenOutbox
from app.core.config import get_settings
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import AuditOutcome
from app.infrastructure.db.ids import uuid7
from app.infrastructure.db.session import create_session_factory
from app.infrastructure.ml_client import (
    DayRecord,
    Indicator,
    IndicatorReport,
    IndicatorsUnavailable,
)
from tests.api_helpers import call, token_for
from tests.api_world import World
from tests.student_helpers import Session, new_student, sleep_body
from tests.therapist_helpers import care_pair, fresh_therapist

pytestmark = pytest.mark.asyncio

DISCLAIMER = "These are wellness indicators. They are not a diagnosis."
AI_CONSENT = "/me/consents/share_ai_signals_with_care_team"


def _ind(name: str, band: Literal["low", "moderate", "elevated"] = "moderate") -> Indicator:
    return Indicator(name, name.title(), "What it means.", "ok", band, band, {"x": 0.4}, "v1")


class FakeIndicators:
    def __init__(self) -> None:
        self.down = False
        self.calls: list[tuple[dt.date, list[DayRecord], list[str]]] = []

    async def indicators(
        self, window_end: dt.date, days: Sequence[DayRecord], notes: Sequence[str]
    ) -> IndicatorReport:
        if self.down:
            raise IndicatorsUnavailable("status 503")
        self.calls.append((window_end, list(days), list(notes)))
        return IndicatorReport(
            (_ind("stress_level"), _ind("burnout_risk", "low"), _ind("sentiment", "elevated")),
            checkin_days=len(days),
            notes_considered=len(notes),
            disclaimer=DISCLAIMER,
        )


@pytest.fixture
def fake() -> FakeIndicators:
    return FakeIndicators()


def _app(api_engine: AsyncEngine, fake: FakeIndicators) -> FastAPI:
    get_settings.cache_clear()
    return create_app(
        get_settings(),
        session_factory=create_session_factory(api_engine),
        delivery=InMemoryTokenOutbox(),
        limiter=SlidingWindowRateLimiter(1_000_000),
        indicator_client=fake,
    )


@pytest_asyncio.fixture
async def ic(api_engine: AsyncEngine, fake: FakeIndicators) -> AsyncIterator[httpx.AsyncClient]:
    """A client for an API whose AI service is ``fake``."""
    transport = httpx.ASGITransport(app=_app(api_engine, fake), client=("203.0.113.30", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as c:
        yield c


async def _past_check_in(
    db: AsyncSession, student: Session, days_ago: int, mood: int, *, stress: int | None = None
) -> None:
    at = dt.datetime.now(dt.UTC).replace(hour=12, minute=0) - dt.timedelta(days=days_ago)
    sid, inst = student.id, student.actor.institution_id
    db.add(
        m.MoodEntry(
            id=uuid7(),
            institution_id=inst,
            student_id=sid,
            mood_score=mood,
            emotions=["Lonely", "calm"],
            logged_at=at,
        )
    )
    if stress is not None:
        db.add(
            m.StressAssessment(
                id=uuid7(),
                institution_id=inst,
                student_id=sid,
                scale="daily_stress_check",
                score=Decimal(stress),
                max_score=Decimal(5),
                perceived_stress_level=stress,
                stressors=["career", "exams"],
                completed_at=at,
            )
        )
    await db.commit()


async def test_a_student_sees_their_own_indicators_from_their_own_check_ins(
    ic: httpx.AsyncClient, api_db: AsyncSession, world: World, fake: FakeIndicators
) -> None:
    me = await new_student(ic, api_db, world)
    someone_else = await new_student(ic, api_db, world)
    r = await me.post(
        "/me/check-ins",
        {
            "mood_score": 2,
            "energy_level": 3,
            "emotions": ["anxious"],
            "note": "Worried about the viva",
            "stress_level": 4,
            "stressors": ["exams"],
            "sleep": sleep_body(hours=6, quality=2),
        },
    )
    assert r.status_code == 201, r.text
    await _past_check_in(api_db, me, 3, 2)
    await _past_check_in(api_db, me, 3, 5, stress=3)  # two check-ins on one day
    await _past_check_in(api_db, me, 40, 1)  # older than the 28 days
    await someone_else.post("/me/check-ins", {"mood_score": 1, "note": "NOT-MINE"})

    r = await me.get("/me/wellness/indicators")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["disclaimer"] == DISCLAIMER
    assert [i["indicator"] for i in body["indicators"]] == [
        "stress_level",
        "burnout_risk",
        "sentiment",
    ]
    assert body["notes_considered"] == 1
    window = dt.date.fromisoformat(body["window_end"]) - dt.date.fromisoformat(body["window_start"])
    assert window.days == 27
    assert "probabilities" not in body["indicators"][0]  # bands only, no raw scores

    window_end, days, notes = fake.calls[-1]
    assert notes == ["Worried about the viva"]
    by_day = {d.day: d for d in days}
    assert all(window_end - dt.timedelta(days=27) <= d <= window_end for d in by_day)
    today = by_day[window_end]
    assert today.mood == 2 and today.energy == 3 and today.stress == 4
    assert today.emotions == ("anxious",) and today.stressors == ("exams",)
    slept = [d for d in days if d.sleep_minutes is not None]
    assert len(slept) == 1 and slept[0].sleep_minutes == 360 and slept[0].sleep_quality == 2
    assert slept[0].bedtime_hour == 0.5  # 06:30 wake after six hours, in UTC
    past = by_day[window_end - dt.timedelta(days=3)]
    assert past.mood == 4  # (2 + 5) / 2, rounded half up
    assert past.stress == 3 and past.stressors == ("career", "exams")
    assert past.emotions == ("calm", "lonely")
    assert len(days) <= 3  # the 40-day-old entry and the other student are not sent


async def test_a_therapist_needs_the_ai_signals_consent_and_never_gets_note_tone(
    ic: httpx.AsyncClient, api_db: AsyncSession, world: World, fake: FakeIndicators
) -> None:
    pair = await care_pair(ic, api_db, world, mood=True, assessments=True)
    await pair.student.post("/me/check-ins", {"mood_score": 2, "note": "PRIVATE-NOTE"})
    path = f"/therapist/students/{pair.student.id}/indicators"
    assert (await pair.therapist.get(path)).status_code == 403  # other consents are not enough
    assert fake.calls == []

    await pair.student.put(AI_CONSENT, {"granted": True})
    r = await pair.therapist.get(path)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [i["indicator"] for i in body["indicators"]] == ["stress_level", "burnout_risk"]
    assert body["notes_considered"] == 0
    assert "PRIVATE-NOTE" not in r.text
    assert fake.calls[-1][2] == []  # the notes were not even sent

    audit = (
        await api_db.scalars(
            select(m.AuditLog).where(
                m.AuditLog.action == "wellness_indicator.read",
                m.AuditLog.subject_student_id == pair.student.id,
                m.AuditLog.outcome == AuditOutcome.ALLOWED,
            )
        )
    ).all()
    assert len(audit) == 1 and audit[0].actor_id == pair.therapist.id
    assert set(audit[0].details) == {"checkin_days", "indicators"}

    await pair.student.put(AI_CONSENT, {"granted": False})
    assert (await pair.therapist.get(path)).status_code == 403


async def test_students_outside_my_care_team_look_like_they_do_not_exist(
    ic: httpx.AsyncClient, api_db: AsyncSession, world: World, fake: FakeIndicators
) -> None:
    pair = await care_pair(ic, api_db, world)
    await pair.student.put(AI_CONSENT, {"granted": True})
    other = await fresh_therapist(ic, api_db, world)
    b_therapist = await fresh_therapist(ic, api_db, world, other_tenant=True)
    for who in (other, b_therapist):
        r = await who.get(f"/therapist/students/{pair.student.id}/indicators")
        assert r.status_code == 404
    assert fake.calls == []


@pytest.mark.parametrize("role", ["teacher", "admin"])
async def test_teachers_and_administrators_are_refused(
    ic: httpx.AsyncClient, api_db: AsyncSession, world: World, fake: FakeIndicators, role: str
) -> None:
    pair = await care_pair(ic, api_db, world)
    await pair.student.put(AI_CONSENT, {"granted": True})
    token = await token_for(ic, getattr(world, role), world.password)
    for path in (f"/therapist/students/{pair.student.id}/indicators", "/me/wellness/indicators"):
        r = await call(ic, "GET", path, token=token)
        assert r.status_code == 403, (role, path, r.text)
    # a therapist has no "own" indicators either
    assert (await pair.therapist.get("/me/wellness/indicators")).status_code == 403
    assert fake.calls == []


async def test_without_the_ai_service_the_answer_is_503_after_access_is_checked(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    pair = await care_pair(client, api_db, world)
    r = await pair.student.get("/me/wellness/indicators")
    assert r.status_code == 503
    assert r.headers["content-type"].startswith("application/problem+json")
    path = f"/therapist/students/{pair.student.id}/indicators"
    assert (await pair.therapist.get(path)).status_code == 403  # consent is checked first
    await pair.student.put(AI_CONSENT, {"granted": True})
    assert (await pair.therapist.get(path)).status_code == 503


async def test_a_failing_ai_service_is_503_and_reveals_nothing(
    ic: httpx.AsyncClient, api_db: AsyncSession, world: World, fake: FakeIndicators
) -> None:
    me = await new_student(ic, api_db, world)
    await me.post("/me/check-ins", {"mood_score": 3, "note": "SECRET-TEXT"})
    fake.down = True
    r = await me.get("/me/wellness/indicators")
    assert r.status_code == 503
    assert "SECRET-TEXT" not in r.text and "503" not in r.json()["detail"]
