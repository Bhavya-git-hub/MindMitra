"""Wellness goals and rule-based recommendations: behaviour and privacy."""

import datetime as dt

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db import models as m
from app.infrastructure.db.enums import AuditOutcome
from app.infrastructure.db.ids import uuid7
from tests.api_world import World
from tests.student_helpers import new_student

pytestmark = pytest.mark.asyncio


# ---- goals ----------------------------------------------------------------------------------


async def test_goal_lifecycle(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    r = await s.post(
        "/me/goals",
        {
            "title": "  Walk   20 minutes ",
            "category": "movement",
            "target_value": 5,
            "unit": "days",
        },
    )
    assert r.status_code == 201, r.text
    goal = r.json()
    assert goal["title"] == "Walk 20 minutes" and goal["status"] == "active"
    assert goal["progress_percent"] == 0

    half = (await s.patch(f"/me/goals/{goal['id']}", {"current_value": 2})).json()
    assert half["progress_percent"] == 40 and half["status"] == "active"
    paused = (await s.patch(f"/me/goals/{goal['id']}", {"status": "paused"})).json()
    assert paused["status"] == "paused"
    resumed = (await s.patch(f"/me/goals/{goal['id']}", {"status": "active"})).json()
    done = (await s.patch(f"/me/goals/{goal['id']}", {"current_value": 5})).json()
    assert resumed["status"] == "active"
    assert done["status"] == "completed" and done["completed_at"] is not None  # reached the target
    reopened = (
        await s.patch(f"/me/goals/{goal['id']}", {"status": "active", "current_value": 1})
    ).json()
    assert reopened["status"] == "active" and reopened["completed_at"] is None

    assert [g["id"] for g in (await s.get("/me/goals?status=active")).json()] == [goal["id"]]
    assert (await s.get("/me/goals?status=completed")).json() == []


async def test_goal_validation(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    for bad in (
        {"title": "", "category": "sleep"},
        {"title": "x", "category": "world-domination"},
        {"title": "x", "category": "sleep", "target_value": 0},
        {"title": "x", "category": "sleep", "target_date": yesterday},
        {"title": "x" * 201, "category": "sleep"},
    ):
        assert (await s.post("/me/goals", bad)).status_code == 422, bad
    assert (await s.get("/me/goals")).json() == []


async def test_active_goals_are_capped(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    for i in range(10):
        assert (
            await s.post("/me/goals", {"title": f"g{i}", "category": "other"})
        ).status_code == 201
    r = await s.post("/me/goals", {"title": "one too many", "category": "other"})
    assert r.status_code == 422 and "10 active goals" in r.json()["detail"]


async def test_goals_are_private_to_their_owner(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    a = await new_student(client, api_db, world)
    b = await new_student(client, api_db, world)
    goal = (await a.post("/me/goals", {"title": "A's goal", "category": "sleep"})).json()

    assert (await b.get("/me/goals")).json() == []
    r = await b.patch(f"/me/goals/{goal['id']}", {"current_value": 3, "title": "hijacked"})
    assert r.status_code == 404  # indistinguishable from a goal that does not exist
    again = (await a.get("/me/goals")).json()
    assert again[0]["title"] == "A's goal" and again[0]["current_value"] == 0

    denial = await api_db.scalar(
        select(func.count())
        .select_from(m.AuditLog)
        .where(
            m.AuditLog.actor_id == b.id,
            m.AuditLog.action == "goal.update",
            m.AuditLog.outcome == AuditOutcome.DENIED,
        )
    )
    assert denial == 1  # the attempt is on record
    assert (await b.patch(f"/me/goals/{uuid7()}", {"current_value": 1})).status_code == 404


async def test_another_institutions_student_cannot_touch_a_goal(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    a = await new_student(client, api_db, world)
    outsider = await new_student(client, api_db, world, other_tenant=True)
    goal = (await a.post("/me/goals", {"title": "mine", "category": "sleep"})).json()
    assert (
        await outsider.patch(f"/me/goals/{goal['id']}", {"status": "abandoned"})
    ).status_code == 404


# ---- recommendations ------------------------------------------------------------------------


async def _log_week(
    db: AsyncSession,
    world: World,
    student_id: object,
    *,
    mood: int,
    stress: int,
    sleep_minutes: int,
) -> None:
    now = dt.datetime.now(dt.UTC)
    for d in range(5):
        day = now - dt.timedelta(days=d)
        db.add(
            m.MoodEntry(
                id=uuid7(),
                institution_id=world.inst_a,
                student_id=student_id,
                mood_score=mood,
                emotions=[],
                logged_at=day,
            )
        )
        db.add(
            m.StressAssessment(
                id=uuid7(),
                institution_id=world.inst_a,
                student_id=student_id,
                scale="daily_stress_check",
                score=stress,
                max_score=5,
                perceived_stress_level=stress,
                stressors=[],
                completed_at=day,
            )
        )
        bed = (day - dt.timedelta(days=1)).replace(hour=23, minute=0)
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
                quality=2,
            )
        )
    await db.commit()


async def test_recommendations_follow_what_the_student_reported(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await _log_week(api_db, world, s.id, mood=2, stress=5, sleep_minutes=300)
    r = await s.post("/me/recommendations/refresh")
    assert r.status_code == 200, r.text
    recs = r.json()
    titles = {x["title"] for x in recs}
    assert "Try a short exercise to settle your stress" in titles
    assert "Ease into a better wind-down" in titles
    assert "Consider talking with someone" in titles
    assert "Set one small wellness goal" in titles
    for rec in recs:
        assert rec["source"] == "rule"
        assert rec["rationale"]  # every suggestion says why
        assert "not advice" in rec["disclaimer"]
        low = (rec["title"] + rec["rationale"]).lower()
        assert not any(w in low for w in ("depress", "anxiety disorder", "diagnos", "you have "))
    stress = next(x for x in recs if x["title"].startswith("Try a short exercise"))
    assert stress["resource"] is not None  # attached to a vetted, published resource

    again = (await s.post("/me/recommendations/refresh")).json()
    assert len(again) == len(recs)  # refreshing twice adds nothing new


async def test_a_calm_week_gets_no_wellbeing_warnings(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await _log_week(api_db, world, s.id, mood=4, stress=2, sleep_minutes=450)
    await s.post("/me/goals", {"title": "Keep going", "category": "mindfulness"})
    titles = {x["title"] for x in (await s.post("/me/recommendations/refresh")).json()}
    assert titles == set()


async def test_responding_to_a_recommendation(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    s = await new_student(client, api_db, world)
    await _log_week(api_db, world, s.id, mood=2, stress=2, sleep_minutes=450)
    recs = (await s.post("/me/recommendations/refresh")).json()
    target = next(x for x in recs if x["title"] == "Consider talking with someone")
    viewed = (await s.patch(f"/me/recommendations/{target['id']}", {"status": "viewed"})).json()
    assert viewed["status"] == "viewed"
    dismissed = await s.patch(f"/me/recommendations/{target['id']}", {"status": "dismissed"})
    assert dismissed.json()["status"] == "dismissed"
    assert target["id"] not in {x["id"] for x in (await s.get("/me/recommendations")).json()}
    closed = (await s.get("/me/recommendations?include_closed=true")).json()
    assert target["id"] in {x["id"] for x in closed}
    assert (
        await s.patch(f"/me/recommendations/{target['id']}", {"status": "pending"})
    ).status_code == 422


async def test_recommendations_are_private_and_only_published_resources_are_attached(
    client: httpx.AsyncClient, api_db: AsyncSession, world: World
) -> None:
    a = await new_student(client, api_db, world)
    b = await new_student(client, api_db, world)
    await _log_week(api_db, world, a.id, mood=2, stress=5, sleep_minutes=300)
    recs = (await a.post("/me/recommendations/refresh")).json()
    assert (await b.get("/me/recommendations")).json() == []
    r = await b.patch(f"/me/recommendations/{recs[0]['id']}", {"status": "completed"})
    assert r.status_code == 404
    ids = {x["resource"]["id"] for x in recs if x["resource"]}
    published = {
        str(rid)
        for rid in await api_db.scalars(
            select(m.Resource.id).where(m.Resource.is_published.is_(True))
        )
    }
    assert ids <= published
