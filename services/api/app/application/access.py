"""Turning policy decisions into errors the API understands, plus shared lookups."""

import dataclasses
import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.auth.policies import Decision
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import ConsentScope


@dataclasses.dataclass
class AccessDenied(Exception):
    """A resource policy said no. The API answers 403, or 404 when ``decision.hide``,
    and records the denial in the audit log."""

    decision: Decision
    action: str
    resource_type: str
    resource_id: uuid.UUID | None = None
    subject_student_id: uuid.UUID | None = None


class NotFound(Exception):
    """The resource does not exist (indistinguishable from a hidden one for the caller)."""


def enforce(
    decision: Decision,
    *,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None = None,
    subject_student_id: uuid.UUID | None = None,
) -> None:
    if not decision.allowed:
        raise AccessDenied(decision, action, resource_type, resource_id, subject_student_id)


async def has_active_care_link(
    db: AsyncSession, *, therapist_id: uuid.UUID, student_id: uuid.UUID, now: dt.datetime
) -> bool:
    row = await db.scalar(
        select(m.CareTeamMember.id).where(
            m.CareTeamMember.therapist_id == therapist_id,
            m.CareTeamMember.student_id == student_id,
            m.CareTeamMember.starts_at <= now,
            (m.CareTeamMember.ends_at.is_(None)) | (m.CareTeamMember.ends_at > now),
        )
    )
    return row is not None


async def has_active_consent(db: AsyncSession, *, user_id: uuid.UUID, scope: ConsentScope) -> bool:
    row = await db.scalar(
        select(m.Consent.id).where(
            m.Consent.user_id == user_id, m.Consent.scope == scope, m.Consent.revoked_at.is_(None)
        )
    )
    return row is not None
