"""Checks shared by every therapist-portal use case.

A therapist reaches student data only when (1) their professional verification is current and
(2) the student is on their care team. Consent is a third, separate gate for reading wellbeing
data (see the policies). Each check is also made in the route guard's permission layer; these
are the record-level checks.
"""

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.access import AccessDenied, NotFound, enforce, has_active_care_link
from app.application.timeutil import now_utc
from app.domain.auth.policies import Principal, can_access_assigned_student, deny
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import VerificationStatus

VERIFICATION_LABELS = {
    "pending": "Waiting for verification",
    "verified": "Verified",
    "rejected": "Not verified",
    "expired": "Licence expired",
}


def effective_verification(therapist: m.Therapist, today: dt.date | None = None) -> str:
    """The stored status, except that a verified therapist whose licence has lapsed is
    ``expired`` (derived on read so nothing has to run at midnight)."""
    today = today or now_utc().date()
    if (
        therapist.verification_status is VerificationStatus.VERIFIED
        and therapist.licence_expires_on is not None
        and therapist.licence_expires_on < today
    ):
        return "expired"
    return therapist.verification_status.value


def is_verified(therapist: m.Therapist, today: dt.date | None = None) -> bool:
    return effective_verification(therapist, today) == "verified"


async def own_therapist(db: AsyncSession, actor: Principal) -> m.Therapist:
    therapist = await db.get(m.Therapist, actor.user_id)
    if therapist is None or therapist.institution_id != actor.institution_id:
        raise NotFound
    return therapist


async def require_verified(db: AsyncSession, actor: Principal, action: str) -> m.Therapist:
    """Care work (students, notes, sessions, alerts, messages) needs a current verification."""
    therapist = await own_therapist(db, actor)
    if not is_verified(therapist):
        raise AccessDenied(
            deny("therapist_not_verified"),
            action=action,
            resource_type="therapist",
            resource_id=actor.user_id,
        )
    return therapist


async def student_in_care(
    db: AsyncSession, actor: Principal, student_id: uuid.UUID, *, action: str, resource_type: str
) -> m.Student:
    """The student, if (and only if) the caller is verified and the student is on their care
    team. Other institutions' and unrelated students are indistinguishable from missing ones."""
    await require_verified(db, actor, action)
    student = await db.get(m.Student, student_id)
    if student is None or student.institution_id != actor.institution_id:
        raise NotFound
    linked = await has_active_care_link(
        db, therapist_id=actor.user_id, student_id=student_id, now=now_utc()
    )
    enforce(
        can_access_assigned_student(
            actor, student_institution_id=student.institution_id, has_active_care_link=linked
        ),
        action=action,
        resource_type=resource_type,
        subject_student_id=student_id,
    )
    return student


async def require_care_link(
    db: AsyncSession,
    actor: Principal,
    *,
    student_id: uuid.UUID,
    institution_id: uuid.UUID,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None = None,
) -> None:
    """A therapist's own record about a student (a session, a follow-up) stays usable only
    while the student is on their care team: ending the link ends access (ADR 0006). Once it
    has ended, the record looks missing."""
    linked = await has_active_care_link(
        db, therapist_id=actor.user_id, student_id=student_id, now=now_utc()
    )
    enforce(
        can_access_assigned_student(
            actor, student_institution_id=institution_id, has_active_care_link=linked
        ),
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        subject_student_id=student_id,
    )


def active_students(actor: Principal) -> Select[Any]:
    """Ids of the students currently on the caller's care team (a sub-select for ``IN``)."""
    now = now_utc()
    return select(m.CareTeamMember.student_id).where(
        m.CareTeamMember.therapist_id == actor.user_id,
        m.CareTeamMember.institution_id == actor.institution_id,
        m.CareTeamMember.starts_at <= now,
        or_(m.CareTeamMember.ends_at.is_(None), m.CareTeamMember.ends_at > now),
    )
