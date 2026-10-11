"""A student's own wellbeing: check-ins, mood, stress, sleep, summaries, goals, recommendations.

Every route is guarded by a permission that only the student role holds, and every use case
scopes its queries to the caller. There is no student id in any path: the caller is the owner.
"""

import datetime as dt
import logging
import uuid
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import app_state, get_db, require_permission
from app.api.routes.me import MoodEntryOut
from app.api.schemas import student as s
from app.api.schemas.indicators import IndicatorsOut, indicators_out
from app.api.zone import Zone, since_days
from app.application import (
    booking,
    goals,
    recommendations,
    student_wellness,
    wellness_indicators,
)
from app.application.timeutil import local_today
from app.domain.auth.permissions import Permission
from app.domain.auth.policies import Principal
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import GoalStatus, RecommendationStatus

log = logging.getLogger("mindmitra.student")

router = APIRouter(prefix="/me", tags=["student"])
Db = Annotated[AsyncSession, Depends(get_db)]
Reader = Annotated[Principal, Depends(require_permission(Permission.WELLNESS_READ_OWN))]
Writer = Annotated[Principal, Depends(require_permission(Permission.WELLNESS_WRITE_OWN))]
GoalManager = Annotated[Principal, Depends(require_permission(Permission.GOAL_MANAGE_OWN))]
RecManager = Annotated[Principal, Depends(require_permission(Permission.RECOMMENDATION_MANAGE_OWN))]
Limit = Annotated[int, Query(ge=1, le=200)]


def mood_out(r: m.MoodEntry) -> MoodEntryOut:
    return MoodEntryOut(
        id=r.id,
        mood_score=r.mood_score,
        energy_level=r.energy_level,
        emotions=list(r.emotions),
        note=r.note,
        logged_at=r.logged_at,
    )


def _sleep_in(data: s.SleepIn | None) -> student_wellness.SleepInput | None:
    if data is None:
        return None
    return student_wellness.SleepInput(data.bedtime, data.wake_time, data.quality)


# ---- check-in -------------------------------------------------------------------------------


class CheckInOut(BaseModel):
    mood: MoodEntryOut
    stress: s.StressEntryOut | None
    sleep: s.SleepEntryOut | None
    support: s.SupportInfo | None


async def _refresh_recommendations_quietly(
    db: AsyncSession, actor: Principal, zone: ZoneInfo
) -> None:
    """New self-reports can change what is worth suggesting. A failure here must never lose
    the check-in that was just saved."""
    try:
        await recommendations.refresh_recommendations(db, actor, zone)
    except Exception:
        log.exception("could not refresh recommendations after a check-in")
        await db.rollback()


@router.post("/check-ins", status_code=201)
async def create_check_in(body: s.CheckInIn, db: Db, principal: Writer, zone: Zone) -> CheckInOut:
    result = await student_wellness.record_check_in(
        db,
        principal,
        student_wellness.CheckInInput(
            mood_score=body.mood_score,
            energy_level=body.energy_level,
            emotions=tuple(body.emotions),
            note=body.note,
            stress_level=body.stress_level,
            stressors=tuple(body.stressors),
            sleep=_sleep_in(body.sleep),
        ),
        zone,
    )
    out = CheckInOut(
        mood=mood_out(result.mood),
        stress=s.stress_out(result.stress) if result.stress else None,
        sleep=s.sleep_out(result.sleep) if result.sleep else None,
        support=s.SUPPORT_INFO if result.support_suggested else None,
    )
    await _refresh_recommendations_quietly(db, principal, zone)
    return out


# ---- mood / stress / sleep ------------------------------------------------------------------


@router.post("/wellness/mood-entries", status_code=201)
async def create_mood_entry(
    body: s.MoodEntryIn, db: Db, principal: Writer, zone: Zone
) -> CheckInOut:
    """A mood-only check-in (the quick path)."""
    return await create_check_in(s.CheckInIn(**body.model_dump()), db, principal, zone)


@router.get("/wellness/stress-entries")
async def list_stress_entries(
    db: Db,
    principal: Reader,
    zone: Zone,
    limit: Limit = 50,
    days: Annotated[int | None, Query(ge=1, le=365)] = None,
) -> list[s.StressEntryOut]:
    rows = await student_wellness.list_stress_entries(
        db, principal, limit=limit, since=since_days(days, zone)
    )
    return [s.stress_out(r) for r in rows]


@router.post("/wellness/stress-entries", status_code=201)
async def create_stress_entry(
    body: s.StressEntryIn, db: Db, principal: Writer, zone: Zone
) -> s.StressEntryOut:
    row = await student_wellness.log_stress(db, principal, body.stress_level, tuple(body.stressors))
    await _refresh_recommendations_quietly(db, principal, zone)
    return s.stress_out(row)


@router.get("/wellness/sleep-entries")
async def list_sleep_entries(
    db: Db,
    principal: Reader,
    zone: Zone,
    limit: Limit = 50,
    days: Annotated[int | None, Query(ge=1, le=365)] = None,
) -> list[s.SleepEntryOut]:
    since = local_today(zone) - dt.timedelta(days=days - 1) if days else None
    rows = await student_wellness.list_sleep_entries(db, principal, limit=limit, since=since)
    return [s.sleep_out(r) for r in rows]


@router.put("/wellness/sleep-entries")
async def upsert_sleep_entry(
    body: s.SleepIn, db: Db, principal: Writer, zone: Zone
) -> s.SleepEntryOut:
    """One entry per morning: logging again for the same wake-up date replaces it."""
    row = await student_wellness.log_sleep(
        db, principal, student_wellness.SleepInput(body.bedtime, body.wake_time, body.quality), zone
    )
    await _refresh_recommendations_quietly(db, principal, zone)
    return s.sleep_out(row)


# ---- summary, trends, dashboard -------------------------------------------------------------


@router.get("/wellness/summary")
async def wellness_summary(db: Db, principal: Reader, zone: Zone) -> s.WellnessSummaryOut:
    return s.summary_out(await student_wellness.summary(db, principal, zone))


@router.get("/wellness/trends")
async def wellness_trends(
    db: Db, principal: Reader, zone: Zone, days: Annotated[int, Query(ge=7, le=90)] = 30
) -> s.TrendsOut:
    series = await student_wellness.daily_series(db, principal, days, zone)
    return s.TrendsOut(days=days, points=[s.trend_out(p) for p in series])


@router.get("/wellness/indicators")
async def wellness_indicators_own(
    request: Request, db: Db, principal: Reader, zone: Zone
) -> IndicatorsOut:
    """Wellness indicators from the last 28 days of check-ins. Estimates, not a diagnosis."""
    client = app_state(request).indicators
    return indicators_out(await wellness_indicators.own(db, principal, zone, client))


class DashboardOut(s.WellnessSummaryOut):
    upcoming_appointment: s.StudentAppointmentOut | None
    recent_trends: list[s.TrendPointOut]
    recommendations: list[s.RecommendationOut]


@router.get("/dashboard")
async def dashboard(db: Db, principal: Reader, zone: Zone) -> DashboardOut:
    summary = await student_wellness.summary(db, principal, zone)
    series = await student_wellness.daily_series(db, principal, 7, zone)
    recs = await recommendations.list_recommendations(db, principal, limit=3)
    upcoming = await booking.next_upcoming(db, principal)
    base = s.summary_out(summary)
    return DashboardOut(
        **base.model_dump(),
        upcoming_appointment=s.appointment_view_out(upcoming) if upcoming else None,
        recent_trends=[s.trend_out(p) for p in series],
        recommendations=[s.recommendation_out(r) for r in recs],
    )


# ---- wellness assessment --------------------------------------------------------------------


@router.get("/wellness/assessment")
async def assessment_instrument(
    principal: Annotated[Principal, Depends(require_permission(Permission.WELLNESS_READ_OWN))],
) -> s.InstrumentOut:
    del principal
    return s.instrument_out()


@router.get("/wellness/assessments")
async def list_assessments(
    db: Db, principal: Reader, limit: Limit = 20
) -> list[s.AssessmentSnapshotOut]:
    rows = await student_wellness.list_assessments(db, principal, limit)
    return [s.assessment_out(r) for r in rows]


@router.post("/wellness/assessments", status_code=201)
async def submit_assessment(
    body: s.AssessmentIn, db: Db, principal: Writer, zone: Zone
) -> s.AssessmentSnapshotOut:
    row = await student_wellness.submit_assessment(db, principal, body.responses)
    await _refresh_recommendations_quietly(db, principal, zone)
    return s.assessment_out(row)


# ---- goals ----------------------------------------------------------------------------------


@router.get("/goals")
async def list_goals(
    db: Db, principal: GoalManager, status: GoalStatus | None = None, limit: Limit = 50
) -> list[s.GoalOut]:
    return [s.goal_out(g) for g in await goals.list_goals(db, principal, status, limit)]


@router.post("/goals", status_code=201)
async def create_goal(body: s.GoalIn, db: Db, principal: GoalManager) -> s.GoalOut:
    goal = await goals.create_goal(
        db,
        principal,
        goals.GoalInput(
            title=body.title,
            category=body.category,
            description=body.description,
            target_value=body.target_value,
            unit=body.unit,
            target_date=body.target_date,
        ),
    )
    return s.goal_out(goal)


@router.patch("/goals/{goal_id}")
async def update_goal(
    goal_id: uuid.UUID, body: s.GoalPatchIn, db: Db, principal: GoalManager
) -> s.GoalOut:
    sent = body.model_fields_set
    patch = goals.GoalPatch(
        title=body.title,
        description=body.description if "description" in sent else goals.UNSET,
        current_value=body.current_value,
        target_value=body.target_value if "target_value" in sent else goals.UNSET,
        target_date=body.target_date if "target_date" in sent else goals.UNSET,
        status=GoalStatus(body.status) if body.status else None,
    )
    return s.goal_out(await goals.update_goal(db, principal, goal_id, patch))


# ---- recommendations ------------------------------------------------------------------------


@router.get("/recommendations")
async def list_recommendations(
    db: Db, principal: RecManager, include_closed: bool = False
) -> list[s.RecommendationOut]:
    rows = await recommendations.list_recommendations(db, principal, include_closed=include_closed)
    return [s.recommendation_out(r) for r in rows]


@router.post("/recommendations/refresh")
async def refresh_recommendations(
    db: Db, principal: RecManager, zone: Zone
) -> list[s.RecommendationOut]:
    rows = await recommendations.refresh_recommendations(db, principal, zone)
    return [s.recommendation_out(r) for r in rows]


@router.patch("/recommendations/{recommendation_id}")
async def respond_to_recommendation(
    recommendation_id: uuid.UUID,
    body: s.RecommendationPatchIn,
    db: Db,
    principal: RecManager,
) -> s.RecommendationOut:
    view = await recommendations.respond(
        db, principal, recommendation_id, RecommendationStatus(body.status)
    )
    return s.recommendation_out(view)
