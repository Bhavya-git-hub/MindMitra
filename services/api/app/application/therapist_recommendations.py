"""Suggestions a therapist makes to a student on their care team.

The student sees them next to the rule-based ones, labelled as coming from their therapist, and
can set them aside like any other. Making one reads nothing about the student, so it needs a
care-team link but not the student's data-sharing consent.
"""

import dataclasses
import datetime as dt
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.directory import get_resource
from app.application.errors import InvalidInput
from app.application.recommendations import OPEN_STATUSES
from app.application.therapist_access import student_in_care
from app.application.timeutil import now_utc
from app.domain.auth.policies import Principal
from app.infrastructure.db import models as m
from app.infrastructure.db.audit import append_audit_event
from app.infrastructure.db.enums import (
    AuditOutcome,
    NotificationType,
    RecommendationSource,
    RecommendationStatus,
    UserRole,
)
from app.infrastructure.db.ids import uuid7

TTL = dt.timedelta(days=30)
MAX_OPEN_PER_STUDENT = 5


@dataclasses.dataclass
class MadeRecommendation:
    recommendation: m.Recommendation
    resource: m.Resource | None


async def create(
    db: AsyncSession,
    actor: Principal,
    student_id: uuid.UUID,
    *,
    title: str,
    rationale: str,
    resource_id: uuid.UUID | None,
) -> MadeRecommendation:
    await student_in_care(
        db, actor, student_id, action="recommendation.create", resource_type="recommendation"
    )
    title = " ".join(title.split())
    rationale = rationale.strip()
    if not 3 <= len(title) <= 200:
        raise InvalidInput("Please give the suggestion a short title.")
    if not 3 <= len(rationale) <= 600:
        raise InvalidInput("Please add a short, kind reason (up to 600 characters).")
    resource = await get_resource(db, actor, resource_id) if resource_id else None
    open_now = await db.scalar(
        select(func.count())
        .select_from(m.Recommendation)
        .where(
            m.Recommendation.student_id == student_id,
            m.Recommendation.authored_by == actor.user_id,
            m.Recommendation.status.in_(OPEN_STATUSES),
        )
    )
    if (open_now or 0) >= MAX_OPEN_PER_STUDENT:
        raise InvalidInput(
            f"This student already has {MAX_OPEN_PER_STUDENT} open suggestions from you."
        )
    now = now_utc()
    rec = m.Recommendation(
        id=uuid7(),
        institution_id=actor.institution_id,
        student_id=student_id,
        resource_id=resource.id if resource else None,
        source=RecommendationSource.THERAPIST,
        status=RecommendationStatus.PENDING,
        title=title,
        rationale=rationale,
        expires_at=now + TTL,
        authored_by=actor.user_id,
    )
    db.add(rec)
    db.add(
        m.Notification(
            id=uuid7(),
            institution_id=actor.institution_id,
            user_id=student_id,
            type=NotificationType.RECOMMENDATION,
            title="Your therapist shared a suggestion",
            payload={"recommendation_id": str(rec.id)},
        )
    )
    await db.flush()
    await append_audit_event(
        db,
        institution_id=actor.institution_id,
        actor_id=actor.user_id,
        actor_role=UserRole.THERAPIST,
        action="recommendation.create",
        outcome=AuditOutcome.ALLOWED,
        resource_type="recommendation",
        resource_id=rec.id,
        subject_student_id=student_id,
        details={"has_resource": resource is not None},
    )
    await db.commit()
    return MadeRecommendation(rec, resource)


async def list_made(
    db: AsyncSession, actor: Principal, student_id: uuid.UUID
) -> list[MadeRecommendation]:
    """Only the suggestions this therapist made, with the student's response (done or set aside)."""
    await student_in_care(
        db, actor, student_id, action="recommendation.list", resource_type="recommendation"
    )
    rows = await db.execute(
        select(m.Recommendation, m.Resource)
        .outerjoin(m.Resource, m.Resource.id == m.Recommendation.resource_id)
        .where(
            m.Recommendation.student_id == student_id,
            m.Recommendation.authored_by == actor.user_id,
            m.Recommendation.institution_id == actor.institution_id,
        )
        .order_by(m.Recommendation.created_at.desc())
        .limit(50)
    )
    return [MadeRecommendation(r, res) for r, res in rows.all()]
