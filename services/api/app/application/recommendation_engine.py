"""Makes personalised, non-medical suggestions for a student (ADR 0012).

The engine reads only the student's own records: recent check-ins, goals, course load, their
latest wellbeing check, their preferences and what they said about earlier suggestions. When
the student allows it, the wellness indicator service adds a view of the last four weeks of
check-ins (days only, never what they wrote); if it is slow or down the engine carries on
without it. The scoring itself is in ``domain.wellness.recommender``.

Nothing a student wrote is read here, sent anywhere or logged.
"""

import dataclasses
import datetime as dt
import logging
from collections.abc import Sequence
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.application import recommendation_feedback as prefs_service
from app.application import safety_workflow, wellness_indicators
from app.application.directory import visible_resource_filters
from app.application.recommendations import RecommendationView, list_recommendations
from app.application.student_wellness import authorize_own
from app.application.timeutil import now_utc
from app.domain.auth.policies import Principal
from app.domain.wellness import instruments
from app.domain.wellness.recommender import signals as sig
from app.domain.wellness.recommender.catalog import ALL_TAGS, ENGINE_VERSION
from app.domain.wellness.recommender.learning import Kind, Response
from app.domain.wellness.recommender.ranking import Past, Pick, ResourceOption, rank
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import (
    EnrollmentStatus,
    FeedbackRating,
    FeedbackReason,
    GoalStatus,
    RecommendationSource,
    RecommendationStatus,
)
from app.infrastructure.db.ids import uuid7
from app.infrastructure.ml_client import DayRecord, IndicatorClient

log = logging.getLogger("mindmitra.recommendations")

RECOMMENDATION_TTL = dt.timedelta(days=14)
HISTORY_DAYS = 120  # how far back past suggestions and feedback shape new ones
RESOURCE_POOL = 300


def _days(records: Sequence[DayRecord]) -> list[sig.Day]:
    return [
        sig.Day(
            day=r.day,
            mood=r.mood,
            energy=r.energy,
            stress=r.stress,
            sleep_minutes=r.sleep_minutes,
            sleep_quality=r.sleep_quality,
            bedtime_hour=r.bedtime_hour,
            emotions=r.emotions,
            stressors=r.stressors,
        )
        for r in records
    ]


async def _context(
    db: AsyncSession, actor: Principal, today: dt.date
) -> tuple[sig.Context, str | None]:
    """Year, course load, active goals and the latest wellbeing check. Also the student's
    locale, which only affects which resources are preferred."""
    row = (
        await db.execute(
            select(m.Student.year_of_study, m.Student.locale).where(
                m.Student.user_id == actor.user_id,
                m.Student.institution_id == actor.institution_id,
            )
        )
    ).first()
    year, locale = (row[0], row[1]) if row else (None, None)
    credits = await db.scalar(
        select(func.coalesce(func.sum(m.Course.credits), 0))
        .select_from(m.CourseEnrollment)
        .join(m.Course, m.Course.id == m.CourseEnrollment.course_id)
        .where(
            m.CourseEnrollment.student_id == actor.user_id,
            m.CourseEnrollment.institution_id == actor.institution_id,
            m.CourseEnrollment.status == EnrollmentStatus.ENROLLED,
        )
    )
    goals = await db.scalars(
        select(m.WellnessGoal.category)
        .where(
            m.WellnessGoal.student_id == actor.user_id,
            m.WellnessGoal.institution_id == actor.institution_id,
            m.WellnessGoal.status == GoalStatus.ACTIVE,
        )
        .distinct()
    )
    assessment = await db.scalar(
        select(m.WellnessAssessment.score)
        .where(
            m.WellnessAssessment.student_id == actor.user_id,
            m.WellnessAssessment.institution_id == actor.institution_id,
        )
        .order_by(m.WellnessAssessment.completed_at.desc())
        .limit(1)
    )
    band = None if assessment is None else instruments.band(float(assessment)).key
    ctx = sig.Context(
        today=today,
        year_of_study=year,
        credits=int(credits or 0) or None,
        active_goal_categories=frozenset(g.value for g in goals),
        assessment_band=band,
    )
    return ctx, locale


async def _indicator_bands(
    client: IndicatorClient | None, today: dt.date, records: list[DayRecord]
) -> dict[str, str]:
    """Bands from the indicator models, or nothing. Notes are never sent, so the one indicator
    read from text has nothing to read and is left out."""
    if client is None:
        return {}
    try:
        report = await wellness_indicators.score(client, today, records, [])
    except wellness_indicators.IndicatorsOff:
        log.info("recommendations: indicator service unavailable, continuing without it")
        return {}
    return {
        i.indicator: i.band
        for i in report.indicators
        if i.status == "ok" and i.band is not None and i.indicator != wellness_indicators.NOTE_TONE
    }


def _response(
    kind: Kind, at: dt.datetime, rec: m.Recommendation, reason: FeedbackReason | None
) -> Response:
    return Response(
        kind=kind,
        at=at,
        intervention_key=rec.intervention_key,
        resource_format=rec.resource_format,
        resource_id=rec.resource_id,
        tags=tuple(rec.tags),
        reason=reason.value if reason else None,
    )


async def _past(
    db: AsyncSession, actor: Principal, now: dt.datetime
) -> tuple[list[Past], list[Response]]:
    rows = await db.execute(
        select(m.Recommendation, m.RecommendationFeedback)
        .outerjoin(
            m.RecommendationFeedback,
            m.RecommendationFeedback.recommendation_id == m.Recommendation.id,
        )
        .where(
            m.Recommendation.student_id == actor.user_id,
            m.Recommendation.institution_id == actor.institution_id,
            m.Recommendation.created_at > now - dt.timedelta(days=HISTORY_DAYS),
        )
    )
    past: list[Past] = []
    responses: list[Response] = []
    for rec, fb in rows.all():
        closed = rec.status in (RecommendationStatus.COMPLETED, RecommendationStatus.DISMISSED)
        past.append(
            Past(
                intervention_key=rec.intervention_key,
                resource_id=rec.resource_id,
                created_at=rec.created_at,
                status=rec.status.value,
                expires_at=rec.expires_at,
                responded_at=rec.updated_at if closed else None,
                rating=fb.rating.value if fb else None,
                reason=fb.reason.value if fb and fb.reason else None,
                rated_at=fb.updated_at if fb else None,
            )
        )
        if fb is not None:
            kind: Kind = "helpful" if fb.rating == FeedbackRating.HELPFUL else "not_helpful"
            responses.append(_response(kind, fb.updated_at, rec, fb.reason))
        elif closed:
            # Finishing or setting a suggestion aside counts for a little, but only when the
            # student gave no rating of their own.
            kind = "completed" if rec.status == RecommendationStatus.COMPLETED else "dismissed"
            responses.append(_response(kind, rec.updated_at, rec, None))
    return past, responses


async def _options(db: AsyncSession, actor: Principal) -> list[ResourceOption]:
    rows = await db.scalars(
        select(m.Resource)
        .where(*visible_resource_filters(actor), m.Resource.tags.overlap(sorted(ALL_TAGS)))
        .order_by(m.Resource.title, m.Resource.id)
        .limit(RESOURCE_POOL)
    )
    return [
        ResourceOption(
            id=r.id,
            title=r.title,
            resource_type=r.resource_type.value,
            tags=tuple(r.tags),
            minutes=r.duration_minutes,
            language=r.language,
        )
        for r in rows
    ]


def _reasons(pick: Pick) -> dict[str, Any]:
    """Why this was suggested, as numbers and signal names only."""
    out: dict[str, Any] = {
        "need": round(pick.need, 3),
        "signals": [{"name": d.signal, "value": round(d.value, 2)} for d in pick.drivers[:4]],
        "idea_affinity": pick.idea_affinity,
        "fits_goal": pick.goal_fit,
    }
    if pick.goal_category:
        out["goal_category"] = pick.goal_category
    return out


async def refresh_recommendations(
    db: AsyncSession, actor: Principal, zone: ZoneInfo, client: IndicatorClient | None = None
) -> list[RecommendationView]:
    """Work out what is worth suggesting now, add it, and return the student's open list.
    Nothing new is suggested while the safety system has paused suggestions."""
    authorize_own(db, actor, "recommendation.refresh", "recommendation")
    if await safety_workflow.active_hold(db, actor) is not None:
        return await list_recommendations(db, actor)
    prefs = await prefs_service.load_preferences(db, actor)

    today, records, _ = await wellness_indicators.collect(
        db, actor.user_id, actor.institution_id, zone, with_notes=False
    )
    ctx, locale = await _context(db, actor, today)
    first = sig.build(_days(records), ctx)
    bands: dict[str, str] = {}
    # With too few check-ins nothing is suggested from them, so skip the service call.
    if prefs.use_indicators and first.checkin_days >= sig.MIN_CHECKIN_DAYS:
        bands = await _indicator_bands(client, today, records)
    signals = dataclasses.replace(first, indicators=bands)

    # One refresh per student at a time, so two quick check-ins cannot both add the same idea.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"recommendations:{actor.user_id}"},
    )
    now = now_utc()
    past, responses = await _past(db, actor, now)
    options = await _options(db, actor)
    picks = rank(signals, prefs_service.to_ranking(prefs, locale), past, responses, options, now)

    for pick in picks:
        iv, resource = pick.intervention, pick.resource
        db.add(
            m.Recommendation(
                id=uuid7(),
                institution_id=actor.institution_id,
                student_id=actor.user_id,
                resource_id=resource.id if resource else None,
                source=RecommendationSource.RULE,
                status=RecommendationStatus.PENDING,
                title=iv.title,
                rationale=pick.rationale,
                expires_at=now + RECOMMENDATION_TTL,
                intervention_key=iv.key,
                problem_area=iv.area,
                relevance=pick.score,
                resource_format=resource.resource_type if resource else None,
                tags=list(resource.tags if resource else iv.tags)[:12],
                reasons=_reasons(pick),
                engine_version=ENGINE_VERSION,
            )
        )
    await db.commit()
    return await list_recommendations(db, actor)
