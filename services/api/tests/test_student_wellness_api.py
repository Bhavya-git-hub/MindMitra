"""Check-in, mood, stress, sleep, summary, trends, dashboard and assessment: through the API."""

import datetime as dt
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db import models as m
from app.infrastructure.db.enums import AlertSource
from app.infrastructure.db.ids import uuid7
from tests.api_world import World
from tests.student_helpers import new_student, sleep_body

pytestmark = pytest.mark.asyncio


# ---- dashboard ------------------------------------------------------------------------------


async def test_new_student_dashboard_is_empty_not_invented(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    r = await s.get("/me/dashboard")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["check_in"]["done_today"] is False
    assert body["check_in"]["streak_days"] == 0
    assert body["mood"]["today"] is None and body["mood"]["indicator"] is None
    assert body["stress"]["today"] is None
    assert body["sleep"]["last_night_minutes"] is None
    assert body["wellbeing"] is None
    assert body["upcoming_appointment"] is None
    assert body["recommendations"] == []
    assert len(body["recent_trends"]) == 7
    assert all(p["mood"] is None for p in body["recent_trends"])
    assert "not a diagnosis" in body["disclaimer"]


async def test_dashboard_reflects_a_check_in(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    r = await s.post(
        "/me/check-ins",
        {
            "mood_score": 4,
            "energy_level": 3,
            "emotions": ["calm", "hopeful"],
            "stress_level": 2,
            "stressors": ["exams"],
            "sleep": sleep_body(hours=7.5, quality=4),
        },
    )
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["mood"]["mood_score"] == 4 and out["support"] is None
    assert out["stress"]["stress_level"] == 2
    assert out["sleep"]["duration_minutes"] == 450

    d = (await s.get("/me/dashboard")).json()
    assert d["check_in"]["done_today"] is True
    assert d["check_in"]["streak_days"] == 1
    assert d["check_in"]["emotions_today"] == ["calm", "hopeful"]
    assert d["mood"]["today"] == 4 and d["mood"]["indicator"]["key"] == "positive"
    assert d["stress"]["today"] == 2 and d["stress"]["indicator"]["key"] == "low"
    assert d["sleep"]["last_night_minutes"] == 450 and d["sleep"]["indicator"]["key"] == "rested"
    assert d["recent_trends"][-1]["mood"] == 4


# ---- check-in -------------------------------------------------------------------------------


async def test_check_in_stores_rows_for_the_caller_only(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    a = await new_student(client, api_db, world)
    b = await new_student(client, api_db, world)
    await a.post("/me/check-ins", {"mood_score": 2, "note": "private to A"})
    await b.post("/me/check-ins", {"mood_score": 5})
    rows = (await a.get("/me/wellness/mood-entries")).json()
    assert [r["mood_score"] for r in rows] == [2] and rows[0]["note"] == "private to A"
    rows_b = (await b.get("/me/wellness/mood-entries")).json()
    assert [r["mood_score"] for r in rows_b] == [5]
    stored = await api_db.scalar(
        select(m.MoodEntry.student_id).where(m.MoodEntry.id == rows[0]["id"])
    )
    assert stored == a.id


async def test_check_in_note_is_encrypted_at_rest(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await s.post("/me/check-ins", {"mood_score": 3, "note": "a very private sentence"})
    raw = await api_db.scalar(
        text("SELECT note FROM wellness.mood_entries WHERE student_id = :s"), {"s": s.id}
    )
    assert raw is not None and b"private" not in bytes(raw)


@pytest.mark.parametrize(
    "payload",
    [
        {"mood_score": 0},
        {"mood_score": 6},
        {"mood_score": 3, "energy_level": 9},
        {"mood_score": 3, "stress_level": 0},
        {"mood_score": 3, "emotions": ["x"] * 9},
        {"mood_score": 3, "note": "n" * 2001},
        {"mood_score": 3, "emotions": [""]},
        {"mood_score": 3, "emotions": ["e" * 61]},
        {},
    ],
)
async def test_check_in_validation(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, payload: dict[str, object]
) -> None:
    s = await new_student(client, api_db, world)
    r = await s.post("/me/check-ins", payload)
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
    assert (await s.get("/me/wellness/mood-entries")).json() == []


async def test_check_in_rejects_impossible_sleep(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    good = sleep_body()
    backwards = {**good, "bedtime": good["wake_time"], "wake_time": good["bedtime"]}
    naive = {**good, "bedtime": good["bedtime"][:19]}
    marathon = sleep_body(hours=20)
    soon = dt.datetime.now(dt.UTC) + dt.timedelta(hours=8)
    future = {
        "bedtime": (soon - dt.timedelta(hours=7)).isoformat(),
        "wake_time": soon.isoformat(),
        "quality": 3,
    }
    for bad in (backwards, naive, marathon, future):
        r = await s.post("/me/check-ins", {"mood_score": 3, "sleep": bad})
        assert r.status_code == 422, bad
    # nothing from the rejected check-ins was saved (not even the mood entry)
    assert (await s.get("/me/wellness/mood-entries")).json() == []


async def test_mood_only_path_creates_an_entry_that_lists_back(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    r = await s.post(
        "/me/wellness/mood-entries",
        {"mood_score": 3, "emotions": ["Tired ", "tired", "okay"]},
    )
    assert r.status_code == 201, r.text
    assert r.json()["mood"]["emotions"] == ["tired", "okay"]  # trimmed, lower-cased, de-duplicated
    listed = (await s.get("/me/wellness/mood-entries?days=7&limit=10")).json()
    assert len(listed) == 1 and listed[0]["id"] == r.json()["mood"]["id"]


@pytest.mark.parametrize(
    ("payload", "expect_support"),
    [
        ({"mood_score": 1}, True),
        ({"mood_score": 3, "stress_level": 5}, True),
        ({"mood_score": 3, "note": "Some days I want to die"}, True),
        ({"mood_score": 3, "note": "I could not sleep before the exam"}, False),
        ({"mood_score": 4}, False),
    ],
)
async def test_support_information_is_offered_not_imposed(
    client: httpx.AsyncClient,
    api_db: AsyncSession,
    world: World,
    payload: dict[str, object],
    expect_support: bool,
) -> None:
    s = await new_student(client, api_db, world)
    r = await s.post("/me/check-ins", payload)
    assert r.status_code == 201
    support = r.json()["support"]
    assert (support is not None) is expect_support
    if support:
        assert support["help_path"] == "/student/emergency"
    # showing support information never contacts anyone on its own
    alerts = await api_db.scalar(
        select(func.count()).select_from(m.RiskAlert).where(m.RiskAlert.student_id == s.id)
    )
    assert alerts == 0


async def test_sleep_is_one_entry_per_morning(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    first = await s.put("/me/wellness/sleep-entries", sleep_body(hours=6, quality=2))
    second = await s.put("/me/wellness/sleep-entries", sleep_body(hours=8, quality=5))
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    rows = (await s.get("/me/wellness/sleep-entries")).json()
    assert len(rows) == 1 and rows[0]["duration_minutes"] == 480 and rows[0]["quality"] == 5


async def test_stress_entries_log_and_list(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    r = await s.post("/me/wellness/stress-entries", {"stress_level": 4, "stressors": ["Deadlines"]})
    assert r.status_code == 201 and r.json()["stressors"] == ["deadlines"]
    rows = (await s.get("/me/wellness/stress-entries?days=7")).json()
    assert [x["stress_level"] for x in rows] == [4]
    assert (await s.post("/me/wellness/stress-entries", {"stress_level": 7})).status_code == 422


async def test_unknown_time_zone_is_a_validation_error(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    r = await s.get("/me/dashboard?tz=Mars/Olympus")
    assert r.status_code == 422
    assert (await s.get("/me/dashboard?tz=Asia/Kolkata")).status_code == 200


# ---- summary and trends ---------------------------------------------------------------------


async def _add_moods(
    db: AsyncSession, world: World, student_id: object, scores_by_days_ago: dict[int, list[int]]
) -> None:
    now = dt.datetime.now(dt.UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    for days_ago, scores in scores_by_days_ago.items():
        for i, score in enumerate(scores):
            db.add(
                m.MoodEntry(
                    id=uuid7(),
                    institution_id=world.inst_a,
                    student_id=student_id,
                    mood_score=score,
                    emotions=[],
                    logged_at=now - dt.timedelta(days=days_ago, minutes=i),
                )
            )
    await db.commit()


async def test_trends_are_daily_averages_oldest_first_with_gaps_as_null(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await _add_moods(api_db, world, s.id, {0: [4, 2], 2: [5], 9: [1]})
    t = (await s.get("/me/wellness/trends?days=14")).json()
    pts = t["points"]
    assert t["days"] == 14 and len(pts) == 14
    dates = [p["date"] for p in pts]
    assert dates == sorted(dates)
    assert pts[-1]["mood"] == 3.0  # today: mean of 4 and 2
    assert pts[-3]["mood"] == 5.0
    assert pts[-10]["mood"] == 1.0
    assert pts[-2]["mood"] is None
    assert (await s.get("/me/wellness/trends?days=3")).status_code == 422
    assert (await s.get("/me/wellness/trends?days=400")).status_code == 422


async def test_trend_days_follow_the_students_time_zone(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    # 23:30 UTC is already the next calendar day in Asia/Kolkata (UTC+5:30)
    at = dt.datetime.now(dt.UTC).replace(hour=23, minute=30, second=0, microsecond=0)
    at -= dt.timedelta(days=2)
    api_db.add(
        m.MoodEntry(
            id=uuid7(),
            institution_id=world.inst_a,
            student_id=s.id,
            mood_score=4,
            emotions=[],
            logged_at=at,
        )
    )
    await api_db.commit()
    utc = {
        p["date"] for p in (await s.get("/me/wellness/trends?days=7")).json()["points"] if p["mood"]
    }
    ist = {
        p["date"]
        for p in (await s.get("/me/wellness/trends?days=7&tz=Asia/Kolkata")).json()["points"]
        if p["mood"]
    }
    assert utc == {at.date().isoformat()}
    assert ist == {(at.date() + dt.timedelta(days=1)).isoformat()}


async def test_summary_direction_and_streak(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    # last week low (2), this week high (4); a check-in on each of the last 3 days
    await _add_moods(api_db, world, s.id, {0: [4], 1: [4], 2: [4], 4: [4], 8: [2], 9: [2], 10: [2]})
    d = (await s.get("/me/wellness/summary")).json()
    assert d["mood"]["average_7d"] == 4.0
    assert d["mood"]["direction"] == "up"
    assert d["check_in"]["streak_days"] == 3
    assert d["check_in"]["check_ins_last_7d"] == 4
    assert d["check_in"]["days_since_last"] == 0


# ---- assessment -----------------------------------------------------------------------------


async def test_assessment_is_scored_on_the_server(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    inst = (await s.get("/me/wellness/assessment")).json()
    assert [q["key"] for q in inst["questions"]] == ["q1", "q2", "q3", "q4", "q5"]
    assert [o["value"] for o in inst["options"]] == [0, 1, 2, 3, 4, 5]
    assert "not a diagnosis" in inst["disclaimer"]

    high = (
        await s.post("/me/wellness/assessments", {"responses": {f"q{i}": 5 for i in range(1, 6)}})
    ).json()
    assert high["score"] == 25 and high["percent"] == 100 and high["band"]["key"] == "doing_well"
    low = (
        await s.post("/me/wellness/assessments", {"responses": {f"q{i}": 1 for i in range(1, 6)}})
    ).json()
    assert low["score"] == 5 and low["band"]["key"] == "lower"
    assert "diagnos" not in low["band"]["message"].lower()

    history = (await s.get("/me/wellness/assessments")).json()
    assert [h["score"] for h in history] == [5, 25]  # newest first
    assert (await s.get("/me/dashboard")).json()["wellbeing"]["score"] == 5
    stored = await api_db.scalar(
        select(m.WellnessAssessment.score).where(m.WellnessAssessment.id == low["id"])
    )
    assert stored == Decimal(5)


@pytest.mark.parametrize(
    "responses",
    [
        {},
        {"q1": 1, "q2": 1, "q3": 1, "q4": 1},
        {"q1": 1, "q2": 1, "q3": 1, "q4": 1, "q5": 1, "q6": 1},
        {"q1": 1, "q2": 1, "q3": 1, "q4": 1, "q5": 6},
        {"q1": 1, "q2": 1, "q3": 1, "q4": 1, "q5": -1},
    ],
)
async def test_assessment_rejects_incomplete_or_out_of_range_answers(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World, responses: dict[str, int]
) -> None:
    s = await new_student(client, api_db, world)
    r = await s.post("/me/wellness/assessments", {"responses": responses})
    assert r.status_code == 422
    assert (await s.get("/me/wellness/assessments")).json() == []


async def test_check_in_is_never_attributed_to_another_source(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await s.post("/me/check-ins", {"mood_score": 1, "note": "bad day"})
    sources = list(
        await api_db.scalars(select(m.RiskAlert.source).where(m.RiskAlert.student_id == s.id))
    )
    assert AlertSource.MOOD_ENTRY not in sources  # no silent alerting from a check-in
