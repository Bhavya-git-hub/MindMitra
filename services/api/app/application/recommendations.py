"""Rule-based recommendations for a student, and the student's responses to them."""

import dataclasses
import datetime as dt
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application import student_wellness
from app.application.access import NotFound, enforce
from app.application.directory import visible_resource_filters
from app.application.student_wellness import authorize_own
from app.application.timeutil import now_utc
from app.domain.auth.policies import Principal, can_use_own_student_record
from app.domain.wellness import instruments
from app.domain.wellness import recommendations as rules
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import RecommendationSource, RecommendationStatus
from app.infrastructure.db.ids import uuid7

RECOMMENDATION_TTL = dt.timedelta(days=14)
OPEN_STATUSES = (RecommendationStatus.PENDING, RecommendationStatus.VIEWED)


@dataclasses.dataclass
class RecommendationView:
    recommendation: m.Recommendation
    resource: m.Resource | None


async def _pick_resource(
    db: AsyncSession, actor: Principal, tags: tuple[str, ...]
) -> m.Resource | None:
    if not tags:
        return None
    return await db.scalar(
        select(m.Resource)
        .where(*visible_resource_filters(actor), m.Resource.tags.overlap(list(tags)))
        .order_by(m.Resource.title)
        .limit(1)
    )


async def list_recommendations(
    db: AsyncSession, actor: Principal, *, include_closed: bool = False, limit: int = 50
) -> list[RecommendationView]:
    authorize_own(db, actor, "recommendation.list", "recommendation")
    now = now_utc()
    stmt = (
        select(m.Recommendation, m.Resource)
        .outerjoin(m.Resource, m.Resource.id == m.Recommendation.resource_id)
        .where(
            m.Recommendation.student_id == actor.user_id,
            m.Recommendation.institution_id == actor.institution_id,
        )
    )
    if not include_closed:
        stmt = stmt.where(
            m.Recommendation.status.in_(OPEN_STATUSES),
            or_(m.Recommendation.expires_at.is_(None), m.Recommendation.expires_at > now),
        )
    rows = await db.execute(stmt.order_by(m.Recommendation.created_at.desc()).limit(limit))
    return [RecommendationView(rec, res) for rec, res in rows.all()]


async def refresh_recommendations(
    db: AsyncSession, actor: Principal, zone: ZoneInfo
) -> list[RecommendationView]:
    """Apply the rules to the last week of self-reports and add anything new and relevant."""
    authorize_own(db, actor, "recommendation.refresh", "recommendation")
    s = await student_wellness.summary(db, actor, zone)
    band: str | None = None
    if s.latest_assessment is not None:
        band = instruments.band(float(s.latest_assessment.score)).key
    facts = rules.Facts(
        avg_mood=s.avg_mood_7d,
        avg_stress=s.avg_stress_7d,
        avg_sleep_minutes=s.avg_sleep_minutes_7d,
        days_since_check_in=s.days_since_check_in,
        has_active_goal=s.active_goals > 0,
        latest_assessment_band=band,
    )
    now = now_utc()
    recent = await db.execute(
        select(m.Recommendation.title, m.Recommendation.resource_id).where(
            m.Recommendation.student_id == actor.user_id,
            m.Recommendation.institution_id == actor.institution_id,
            m.Recommendation.created_at > now - RECOMMENDATION_TTL,
        )
    )
    seen_titles: set[str] = set()
    seen_resources: set[uuid.UUID] = set()
    for title, resource_id in recent.all():
        seen_titles.add(title)
        if resource_id is not None:
            seen_resources.add(resource_id)

    created = False
    for suggestion in rules.suggest(facts):
        resource = await _pick_resource(db, actor, suggestion.tags)
        if suggestion.title in seen_titles or (resource and resource.id in seen_resources):
            continue
        db.add(
            m.Recommendation(
                id=uuid7(),
                institution_id=actor.institution_id,
                student_id=actor.user_id,
                resource_id=resource.id if resource else None,
                source=RecommendationSource.RULE,
                status=RecommendationStatus.PENDING,
                title=suggestion.title,
                rationale=suggestion.rationale,
                expires_at=now + RECOMMENDATION_TTL,
            )
        )
        created = True
    if created:
        await db.flush()
        await db.commit()
    return await list_recommendations(db, actor)


async def respond(
    db: AsyncSession,
    actor: Principal,
    recommendation_id: uuid.UUID,
    new_status: RecommendationStatus,
) -> RecommendationView:
    rec = await db.get(m.Recommendation, recommendation_id, with_for_update=True)
    if rec is None:
        raise NotFound
    enforce(
        can_use_own_student_record(
            actor, student_id=rec.student_id, institution_id=rec.institution_id
        ),
        action="recommendation.update",
        resource_type="recommendation",
        resource_id=rec.id,
        subject_student_id=rec.student_id,
    )
    rec.status = new_status
    await db.flush()
    resource = await db.get(m.Resource, rec.resource_id) if rec.resource_id else None
    await db.commit()
    return RecommendationView(rec, resource)
