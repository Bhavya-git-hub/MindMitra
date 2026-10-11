"""The recommendation engine through the API: what is suggested for each problem area, the
"helpful" / "not helpful" loop, history, preferences, and who can see any of it.

The indicator service is replaced by ``FakeIndicators``. All records are synthetic.
"""

import asyncio
import datetime as dt
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.api.main import create_app
from app.api.rate_limit import SlidingWindowRateLimiter
from app.application.auth.delivery import InMemoryTokenOutbox
from app.core.config import get_settings
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import (
    FeedbackRating,
    FeedbackReason,
    RecommendationSource,
    RecommendationStatus,
)
from app.infrastructure.db.ids import uuid7
from app.infrastructure.db.session import create_session_factory
from app.infrastructure.ml_client import (
    DayRecord,
    Indicator,
    IndicatorReport,
    IndicatorsUnavailable,
)
from tests.api_world import World
from tests.student_helpers import Session, new_student

pytestmark = pytest.mark.asyncio

RECS = "/me/recommendations"
MEDICAL = ("depress", "disorder", "diagnos", "medicat", "prescri", "dosage", "symptom", "illness")


async def log_days(
    db: AsyncSession,
    world: World,
    student_id: Any,
    *,
    days: int = 8,
    mood: int = 3,
    energy: int | None = None,
    stress: int | None = None,
    stressors: list[str] | None = None,
    emotions: list[str] | None = None,
    sleep_minutes: int | None = None,
    sleep_quality: int = 3,
    bedtime_hour: int = 23,
) -> None:
    now = dt.datetime.now(dt.UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    for d in range(days):
        day = now - dt.timedelta(days=d)
        db.add(
            m.MoodEntry(
                id=uuid7(),
                institution_id=world.inst_a,
                student_id=student_id,
                mood_score=mood,
                energy_level=energy,
                emotions=emotions or [],
                logged_at=day,
            )
        )
        if stress is not None:
            db.add(
                m.StressAssessment(
                    id=uuid7(),
                    institution_id=world.inst_a,
                    student_id=student_id,
                    scale="daily_stress_check",
                    score=stress,
                    max_score=5,
                    perceived_stress_level=stress,
                    stressors=stressors or [],
                    completed_at=day,
                )
            )
        if sleep_minutes is not None:
            bed = (day - dt.timedelta(days=1)).replace(hour=bedtime_hour, minute=0)
            wake = bed + dt.timedelta(minutes=sleep_minutes)
            db.add(
                m.SleepEntry(
                    id=uuid7(),
                    institution_id=world.inst_a,
                    student_id=student_id,
                    sleep_date=wake.date(),
                    bedtime=bed,
                    wake_time=wake,
                    duration_minutes=sleep_minutes,
                    quality=sleep_quality,
                )
            )
    await db.commit()


async def refresh(s: Session) -> list[dict[str, Any]]:
    r = await s.post(f"{RECS}/refresh")
    assert r.status_code == 200, r.text
    return list(r.json())


def by_area(recs: list[dict[str, Any]], area: str) -> list[dict[str, Any]]:
    return [r for r in recs if r["problem_area"] == area]


# ---- each problem area maps to its own non-medical ideas ------------------------------------


async def test_academic_burnout_is_offered_planning_breaks_and_counselling(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await log_days(
        api_db, world, s.id, energy=1, stress=5, stressors=["exams", "deadlines", "workload"]
    )
    recs = await refresh(s)
    titles = {r["title"] for r in by_area(recs, "academic_burnout")}
    assert "Plan your study weeks" in titles
    assert "Map out your workload" in titles
    assert "Build short breaks into study days" in titles
    counselling = [r for r in recs if r["action"] == "book_counselling"]
    assert len(counselling) == 1
    assert counselling[0]["resource"] is not None  # points at the campus counselling service


async def test_career_anxiety_is_offered_placement_help_and_mentoring(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await log_days(
        api_db, world, s.id, stress=4, stressors=["career"], emotions=["anxious"], mood=3
    )
    recs = await refresh(s)
    titles = {r["title"] for r in by_area(recs, "career_anxiety")}
    assert "Explore placement resources" in titles
    assert "Try a mock interview" in titles
    assert "Talk with a career mentor" in titles


async def test_social_isolation_is_offered_clubs_and_peer_activities(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await log_days(api_db, world, s.id, mood=2, emotions=["lonely"], stress=3)
    recs = await refresh(s)
    titles = {r["title"] for r in by_area(recs, "social_isolation")}
    assert "Look at clubs and societies" in titles
    assert any("peer" in t.lower() or "meet" in t.lower() for t in titles)


async def test_sleep_disruption_is_offered_hygiene_and_scheduling(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await log_days(api_db, world, s.id, sleep_minutes=290, sleep_quality=2, bedtime_hour=2)
    recs = await refresh(s)
    areas = {r["problem_area"] for r in recs}
    assert "sleep_disruption" in areas
    for r in by_area(recs, "sleep_disruption"):
        assert r["resource"] is not None


async def test_suggestions_say_why_and_never_sound_medical(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await log_days(
        api_db,
        world,
        s.id,
        mood=1,
        energy=1,
        stress=5,
        stressors=["exams", "career"],
        emotions=["lonely", "anxious"],
        sleep_minutes=250,
    )
    recs = await refresh(s)
    assert recs
    for r in recs:
        assert r["rationale"]
        assert "not advice" in r["disclaimer"]
        text = f"{r['title']} {r['rationale']}".lower()
        assert not [w for w in MEDICAL if w in text], text
        if r["resource"]:
            assert r["resource"]["url"] is None or r["resource"]["url"].startswith("http")


async def test_a_settled_fortnight_gets_nothing(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await s.post("/me/goals", {"title": "Keep going", "category": "mindfulness"})
    await log_days(
        api_db, world, s.id, mood=4, energy=4, stress=2, sleep_minutes=450, sleep_quality=4
    )
    assert await refresh(s) == []


async def test_a_new_check_in_refreshes_the_list(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await log_days(api_db, world, s.id, days=6, mood=2, emotions=["lonely"], stress=3)
    assert (await s.get(RECS)).json() == []
    r = await s.post("/me/check-ins", {"mood_score": 2, "emotions": ["lonely"]})
    assert r.status_code == 201, r.text
    assert (await s.get(RECS)).json() != []


async def test_refreshing_twice_adds_nothing_and_parallel_refreshes_do_not_duplicate(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await log_days(api_db, world, s.id, energy=1, stress=5, stressors=["exams", "deadlines"])
    first = await refresh(s)
    assert {r["id"] for r in await refresh(s)} == {r["id"] for r in first}
    t = await new_student(client, api_db, world)
    await log_days(api_db, world, t.id, energy=1, stress=5, stressors=["exams", "deadlines"])
    await asyncio.gather(*(t.post(f"{RECS}/refresh") for _ in range(4)))
    keys = list(
        await api_db.scalars(
            select(m.Recommendation.intervention_key).where(m.Recommendation.student_id == t.id)
        )
    )
    assert len(keys) == len(set(keys))


# ---- helpful / not helpful ------------------------------------------------------------------


async def _burnt_out_student(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> tuple[Session, list[dict[str, Any]]]:
    s = await new_student(client, api_db, world)
    await log_days(api_db, world, s.id, energy=1, stress=5, stressors=["exams", "deadlines"])
    return s, await refresh(s)


async def test_a_student_can_say_helpful_and_change_their_mind(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s, recs = await _burnt_out_student(client, api_db, world)
    target = recs[0]
    r = await s.put(f"{RECS}/{target['id']}/feedback", {"rating": "helpful"})
    assert r.status_code == 200, r.text
    assert r.json()["feedback"]["rating"] == "helpful"
    assert r.json()["status"] == target["status"]  # helpful keeps it where it is
    again = await s.put(
        f"{RECS}/{target['id']}/feedback", {"rating": "not_helpful", "reason": "not_now"}
    )
    assert again.json()["feedback"]["rating"] == "not_helpful"
    assert again.json()["feedback"]["reason"] == "not_now"
    count = await api_db.scalar(
        select(func.count())
        .select_from(m.RecommendationFeedback)
        .where(m.RecommendationFeedback.recommendation_id == target["id"])
    )
    assert count == 1  # a second answer replaces the first


async def test_not_helpful_takes_a_suggestion_off_the_open_list_but_keeps_it_in_history(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s, recs = await _burnt_out_student(client, api_db, world)
    target = recs[0]
    r = await s.put(
        f"{RECS}/{target['id']}/feedback", {"rating": "not_helpful", "reason": "not_relevant"}
    )
    assert r.json()["status"] == "dismissed"
    assert target["id"] not in {x["id"] for x in (await s.get(RECS)).json()}
    history = (await s.get(f"{RECS}/history")).json()
    mine = next(x for x in history if x["id"] == target["id"])
    assert mine["feedback"]["reason"] == "not_relevant"


async def test_a_reason_only_goes_with_not_helpful_and_must_be_one_of_the_list(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s, recs = await _burnt_out_student(client, api_db, world)
    url = f"{RECS}/{recs[0]['id']}/feedback"
    assert (await s.put(url, {"rating": "helpful", "reason": "not_now"})).status_code == 422
    assert (await s.put(url, {"rating": "not_helpful", "reason": "free text"})).status_code == 422
    assert (await s.put(url, {"rating": "meh"})).status_code == 422
    assert (await s.put(url, {})).status_code == 422


async def test_a_rating_can_be_taken_back(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s, recs = await _burnt_out_student(client, api_db, world)
    url = f"{RECS}/{recs[0]['id']}/feedback"
    await s.put(url, {"rating": "helpful"})
    r = await s.delete(url)
    assert r.status_code == 200
    assert r.json()["feedback"] is None
    assert (await s.delete(url)).status_code == 200  # nothing to take back is fine


async def test_not_helpful_stops_the_same_idea_coming_straight_back(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s, recs = await _burnt_out_student(client, api_db, world)
    disliked = recs[0]
    row = await api_db.get(m.Recommendation, disliked["id"])
    assert row is not None
    key = row.intervention_key
    await s.put(
        f"{RECS}/{disliked['id']}/feedback", {"rating": "not_helpful", "reason": "not_relevant"}
    )
    for r in await refresh(s):
        again = await api_db.get(m.Recommendation, r["id"])
        assert again is not None
        assert again.intervention_key != key


async def _old_rated(
    db: AsyncSession, world: World, student_id: Any, key: str, rating: FeedbackRating, days: int
) -> None:
    """A suggestion made ``days`` ago and rated then, written directly so it can be dated."""
    at = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
    rec = m.Recommendation(
        id=uuid7(),
        institution_id=world.inst_a,
        student_id=student_id,
        source=RecommendationSource.RULE,
        status=RecommendationStatus.COMPLETED
        if rating == FeedbackRating.HELPFUL
        else RecommendationStatus.DISMISSED,
        title="earlier",
        rationale="earlier",
        intervention_key=key,
        problem_area="academic_burnout",
        resource_format="article",
        tags=["breaks", "movement"],
        created_at=at,
        updated_at=at,
        expires_at=at + dt.timedelta(days=14),
    )
    db.add(rec)
    await db.flush()
    db.add(
        m.RecommendationFeedback(
            institution_id=world.inst_a,
            student_id=student_id,
            recommendation_id=rec.id,
            rating=rating,
            reason=FeedbackReason.NOT_RELEVANT if rating == FeedbackRating.NOT_HELPFUL else None,
            created_at=at,
            updated_at=at,
        )
    )
    await db.commit()


async def _affinity(db: AsyncSession, recs: list[dict[str, Any]], key: str) -> float | None:
    for r in recs:
        row = await db.get(m.Recommendation, r["id"])
        if row and row.intervention_key == key and row.reasons:
            return float(row.reasons["idea_affinity"])
    return None


async def test_past_feedback_changes_how_an_idea_is_weighed_next_time(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    data: dict[str, Any] = {"energy": 1, "stress": 5, "stressors": ["exams", "deadlines"]}
    plain = await new_student(client, api_db, world)
    await log_days(api_db, world, plain.id, **data)
    loved = await new_student(client, api_db, world)
    await log_days(api_db, world, loved.id, **data)
    for _ in range(2):
        await _old_rated(api_db, world, loved.id, "scheduled_breaks", FeedbackRating.HELPFUL, 40)
    disliked = await new_student(client, api_db, world)
    await log_days(api_db, world, disliked.id, **data)
    for _ in range(2):
        await _old_rated(
            api_db, world, disliked.id, "scheduled_breaks", FeedbackRating.NOT_HELPFUL, 40
        )

    baseline = await _affinity(api_db, await refresh(plain), "scheduled_breaks")
    up = await _affinity(api_db, await refresh(loved), "scheduled_breaks")
    down = await _affinity(api_db, await refresh(disliked), "scheduled_breaks")
    assert baseline == 1.0
    assert up is not None and up > 1.0
    assert down is None or down < 1.0


async def test_feedback_is_never_pooled_across_students(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    data: dict[str, Any] = {"energy": 1, "stress": 5, "stressors": ["exams", "deadlines"]}
    noisy = await new_student(client, api_db, world)
    quiet = await new_student(client, api_db, world)
    await log_days(api_db, world, noisy.id, **data)
    await log_days(api_db, world, quiet.id, **data)
    for _ in range(5):
        await _old_rated(api_db, world, noisy.id, "study_planning", FeedbackRating.NOT_HELPFUL, 40)
    assert await _affinity(api_db, await refresh(quiet), "study_planning") == 1.0


async def test_nobody_else_can_rate_or_read_my_suggestions(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s, recs = await _burnt_out_student(client, api_db, world)
    other = await new_student(client, api_db, world)
    abroad = await new_student(client, api_db, world, other_tenant=True)
    url = f"{RECS}/{recs[0]['id']}/feedback"
    for intruder in (other, abroad):
        assert (await intruder.put(url, {"rating": "helpful"})).status_code == 404
        assert (await intruder.delete(url)).status_code == 404
        assert (await intruder.get(f"{RECS}/history")).json() == []
    assert (await s.get(f"{RECS}/history")).status_code == 200


# ---- history --------------------------------------------------------------------------------


async def test_history_lists_everything_newest_first_and_pages(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s, recs = await _burnt_out_student(client, api_db, world)
    await s.patch(f"{RECS}/{recs[0]['id']}", {"status": "dismissed"})
    history = (await s.get(f"{RECS}/history")).json()
    assert {r["id"] for r in history} == {r["id"] for r in recs}
    stamps = [r["created_at"] for r in history]
    assert stamps == sorted(stamps, reverse=True)
    page = (await s.get(f"{RECS}/history?limit=2")).json()
    assert len(page) == 2
    rest = (await s.get(f"{RECS}/history?before={page[-1]['created_at']}")).json()
    assert {r["id"] for r in page} | {r["id"] for r in rest} <= {r["id"] for r in recs}
    assert (await s.get(f"{RECS}/history?limit=0")).status_code == 422
    assert (await s.get(f"{RECS}/history?limit=101")).status_code == 422


# ---- preferences ----------------------------------------------------------------------------


async def test_preferences_start_at_the_defaults_and_can_be_changed(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    first = (await s.get(f"{RECS}/preferences")).json()
    assert first["preferred_formats"] == []
    assert first["max_minutes"] is None
    assert first["muted_areas"] == []
    assert first["use_indicators"] is True
    assert "video" in first["available_formats"]
    assert "counselling" in first["available_areas"]
    r = await s.patch(
        f"{RECS}/preferences",
        {"preferred_formats": ["video", "audio"], "max_minutes": 10, "use_indicators": False},
    )
    assert r.status_code == 200, r.text
    assert r.json()["preferred_formats"] == ["audio", "video"]
    assert r.json()["max_minutes"] == 10
    assert r.json()["use_indicators"] is False
    cleared = await s.patch(f"{RECS}/preferences", {"max_minutes": None})
    assert cleared.json()["max_minutes"] is None
    assert cleared.json()["preferred_formats"] == ["audio", "video"]  # untouched


@pytest.mark.parametrize(
    "body",
    [
        {"preferred_formats": ["hologram"]},
        {"muted_areas": ["engagement"]},
        {"muted_areas": ["feelings"]},
        {"max_minutes": 0},
        {"max_minutes": 181},
    ],
)
async def test_unknown_preferences_are_refused(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, body: dict[str, Any]
) -> None:
    s = await new_student(client, api_db, world)
    assert (await s.patch(f"{RECS}/preferences", body)).status_code == 422


async def test_muting_a_topic_stops_suggestions_for_it(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await s.patch(f"{RECS}/preferences", {"muted_areas": ["social_isolation", "counselling"]})
    await log_days(api_db, world, s.id, mood=2, emotions=["lonely"], stress=4, energy=1,
                   stressors=["exams", "deadlines"])  # fmt: skip
    recs = await refresh(s)
    assert recs
    assert not by_area(recs, "social_isolation")
    assert not [r for r in recs if r["action"] == "book_counselling"]


async def test_a_time_limit_steers_towards_shorter_resources(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await s.patch(f"{RECS}/preferences", {"max_minutes": 5})
    await log_days(api_db, world, s.id, sleep_minutes=290, sleep_quality=2, bedtime_hour=2)
    for r in await refresh(s):
        res = r["resource"]
        if res and res["duration_minutes"]:
            assert res["duration_minutes"] <= 10


# ---- the indicator service ------------------------------------------------------------------


def _ind(name: str, band: str) -> Indicator:
    return Indicator(name, name.title(), "What it means.", "ok", band, band, {}, "v1")  # type: ignore[arg-type]


class FakeIndicators:
    def __init__(self) -> None:
        self.down = False
        self.bands: dict[str, str] = {}
        self.calls: list[tuple[list[DayRecord], list[str]]] = []

    async def indicators(
        self, window_end: dt.date, days: Sequence[DayRecord], notes: Sequence[str]
    ) -> IndicatorReport:
        if self.down:
            raise IndicatorsUnavailable("status 503")
        self.calls.append((list(days), list(notes)))
        return IndicatorReport(
            tuple(_ind(k, v) for k, v in self.bands.items()),
            len(days),
            len(notes),
            "Not a diagnosis.",
        )


@pytest.fixture
def fake() -> FakeIndicators:
    return FakeIndicators()


@pytest_asyncio.fixture
async def ic(api_engine: AsyncEngine, fake: FakeIndicators) -> AsyncIterator[httpx.AsyncClient]:
    get_settings.cache_clear()
    app: FastAPI = create_app(
        get_settings(),
        session_factory=create_session_factory(api_engine),
        delivery=InMemoryTokenOutbox(),
        limiter=SlidingWindowRateLimiter(1_000_000),
        indicator_client=fake,
    )
    transport = httpx.ASGITransport(app=app, client=("203.0.113.31", 50000))
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as c:
        yield c


async def test_indicators_can_shape_suggestions_and_no_note_is_ever_sent(
    ic: httpx.AsyncClient, fake: FakeIndicators, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(ic, api_db, world)
    fake.bands = {"social_isolation": "elevated"}
    await log_days(api_db, world, s.id, mood=3, stress=2)
    api_db.add(
        m.MoodEntry(
            id=uuid7(),
            institution_id=world.inst_a,
            student_id=s.id,
            mood_score=3,
            note="a very private note",
            logged_at=dt.datetime.now(dt.UTC),
        )
    )
    await api_db.commit()
    recs = await refresh(s)
    assert by_area(recs, "social_isolation")
    assert fake.calls
    assert all(notes == [] for _, notes in fake.calls)


async def test_suggestions_still_work_when_the_indicator_service_is_down(
    ic: httpx.AsyncClient, fake: FakeIndicators, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(ic, api_db, world)
    fake.down = True
    await log_days(api_db, world, s.id, energy=1, stress=5, stressors=["exams", "deadlines"])
    recs = await refresh(s)
    assert by_area(recs, "academic_burnout")


async def test_turning_indicators_off_means_they_are_not_even_asked(
    ic: httpx.AsyncClient, fake: FakeIndicators, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(ic, api_db, world)
    await s.patch(f"{RECS}/preferences", {"use_indicators": False})
    fake.bands = {"social_isolation": "elevated"}
    await log_days(api_db, world, s.id, mood=3, stress=2)
    recs = await refresh(s)
    assert fake.calls == []
    assert not by_area(recs, "social_isolation")


async def test_too_few_check_ins_means_the_indicator_service_is_not_asked(
    ic: httpx.AsyncClient, fake: FakeIndicators, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(ic, api_db, world)
    await log_days(api_db, world, s.id, days=2, mood=1)
    await refresh(s)
    assert fake.calls == []


async def test_indicators_never_raise_an_alert_or_notify_anyone(
    ic: httpx.AsyncClient, fake: FakeIndicators, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(ic, api_db, world)
    fake.bands = {"social_isolation": "elevated", "stress_level": "elevated"}
    await log_days(api_db, world, s.id, mood=3, stress=3)
    alerts_before = await api_db.scalar(select(func.count()).select_from(m.RiskAlert))
    notes_before = await api_db.scalar(select(func.count()).select_from(m.Notification))
    await refresh(s)
    assert await api_db.scalar(select(func.count()).select_from(m.RiskAlert)) == alerts_before
    assert await api_db.scalar(select(func.count()).select_from(m.Notification)) == notes_before


# ---- export ---------------------------------------------------------------------------------


async def test_my_export_includes_my_ratings_and_settings(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s, recs = await _burnt_out_student(client, api_db, world)
    await s.put(f"{RECS}/{recs[0]['id']}/feedback", {"rating": "helpful"})
    await s.patch(f"{RECS}/preferences", {"max_minutes": 15})
    data = (await s.get("/me/privacy/export")).json()
    assert [f["rating"] for f in data["recommendation_feedback"]] == ["helpful"]
    assert data["recommendation_preferences"][0]["max_minutes"] == 15
    assert all("problem_area" in r for r in data["recommendations"])
