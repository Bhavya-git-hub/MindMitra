"""A student's recommendations: what is open now, the full history, and how they respond.

Suggestions are made by ``recommendation_engine``; ratings and preferences live in
``recommendation_feedback``. Everything here is the student's own and nobody else's.

While the safety system has paused normal suggestions (a HIGH or IMMEDIATE concern, ADR 0013),
the open list holds only what a therapist suggested; the history is unchanged.
"""

import dataclasses
import uuid

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application import safety_workflow
from app.application.access import NotFound, enforce
from app.application.student_wellness import authorize_own
from app.application.timeutil import now_utc
from app.domain.auth.policies import Principal, can_use_own_student_record
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import RecommendationSource, RecommendationStatus

OPEN_STATUSES = (RecommendationStatus.PENDING, RecommendationStatus.VIEWED)
MAX_HISTORY = 100


@dataclasses.dataclass
class RecommendationView:
    recommendation: m.Recommendation
    resource: m.Resource | None
    feedback: m.RecommendationFeedback | None = None


def _query(
    actor: Principal,
) -> Select[m.Recommendation, m.Resource, m.RecommendationFeedback]:
    stmt = (
        select(m.Recommendation, m.Resource, m.RecommendationFeedback)
        .outerjoin(m.Resource, m.Resource.id == m.Recommendation.resource_id)
        .outerjoin(
            m.RecommendationFeedback,
            m.RecommendationFeedback.recommendation_id == m.Recommendation.id,
        )
        .where(
            m.Recommendation.student_id == actor.user_id,
            m.Recommendation.institution_id == actor.institution_id,
        )
    )
    return stmt


async def list_recommendations(
    db: AsyncSession,
    actor: Principal,
    *,
    include_closed: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[RecommendationView]:
    """Open suggestions by default; with ``include_closed`` the whole history, newest first.
    Suggestions made in one refresh share a timestamp, so the order breaks ties on id."""
    authorize_own(db, actor, "recommendation.list", "recommendation")
    stmt = _query(actor)
    if not include_closed:
        stmt = stmt.where(
            m.Recommendation.status.in_(OPEN_STATUSES),
            or_(m.Recommendation.expires_at.is_(None), m.Recommendation.expires_at > now_utc()),
        )
        if await safety_workflow.active_hold(db, actor) is not None:
            stmt = stmt.where(m.Recommendation.source == RecommendationSource.THERAPIST)
    rows = await db.execute(
        stmt.order_by(m.Recommendation.created_at.desc(), m.Recommendation.id.desc())
        .offset(offset)
        .limit(min(limit, MAX_HISTORY))
    )
    return [RecommendationView(rec, res, fb) for rec, res, fb in rows.all()]


async def get_view(
    db: AsyncSession, actor: Principal, recommendation_id: uuid.UUID
) -> RecommendationView:
    row = (await db.execute(_query(actor).where(m.Recommendation.id == recommendation_id))).first()
    if row is None:
        raise NotFound
    return RecommendationView(row[0], row[1], row[2])


async def load_own(
    db: AsyncSession, actor: Principal, recommendation_id: uuid.UUID, action: str
) -> m.Recommendation:
    """The suggestion, locked for update, if it belongs to the caller. Anything else is
    indistinguishable from a missing one."""
    rec = await db.get(m.Recommendation, recommendation_id, with_for_update=True)
    if rec is None:
        raise NotFound
    enforce(
        can_use_own_student_record(
            actor, student_id=rec.student_id, institution_id=rec.institution_id
        ),
        action=action,
        resource_type="recommendation",
        resource_id=rec.id,
        subject_student_id=rec.student_id,
    )
    return rec


async def respond(
    db: AsyncSession,
    actor: Principal,
    recommendation_id: uuid.UUID,
    new_status: RecommendationStatus,
) -> RecommendationView:
    rec = await load_own(db, actor, recommendation_id, "recommendation.update")
    rec.status = new_status
    await db.flush()
    view = await get_view(db, actor, rec.id)
    await db.commit()
    return view
