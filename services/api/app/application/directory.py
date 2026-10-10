"""Read-only directories a signed-in student (or therapist) may browse within their own
institution: vetted resources, and therapists' public profiles with open appointment slots.

Only public-profile fields leave this module. Licence numbers, caseload and anything about
other students are never part of the directory.
"""

import dataclasses
import datetime as dt
import uuid

from sqlalchemy import ColumnElement, and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.access import NotFound, has_active_care_link
from app.application.timeutil import now_utc
from app.domain.auth.policies import Principal
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import (
    AppointmentStatus,
    ResourceType,
    UserStatus,
    VerificationStatus,
)

MAX_LIMIT = 100
BOOKING_LEAD_TIME = dt.timedelta(hours=2)
SLOT_WINDOW = dt.timedelta(days=45)


FACULTY_TAG = "faculty"


def visible_resource_filters(
    actor: Principal, *, faculty: bool = False
) -> list[ColumnElement[bool]]:
    """Published, reviewed content that is global or belongs to the caller's institution.

    Content written for staff is tagged ``faculty``: students and therapists never see it, and
    teachers see only that, so each audience gets its own library.
    """
    is_faculty = m.Resource.tags.contains([FACULTY_TAG])
    return [
        m.Resource.is_published.is_(True),
        or_(
            m.Resource.institution_id.is_(None),
            m.Resource.institution_id == actor.institution_id,
        ),
        is_faculty if faculty else ~is_faculty,
    ]


async def list_resources(
    db: AsyncSession,
    actor: Principal,
    *,
    resource_type: ResourceType | None,
    tag: str | None,
    query: str | None,
    limit: int,
    faculty: bool = False,
) -> list[m.Resource]:
    stmt = select(m.Resource).where(*visible_resource_filters(actor, faculty=faculty))
    if resource_type is not None:
        stmt = stmt.where(m.Resource.resource_type == resource_type)
    if tag:
        stmt = stmt.where(m.Resource.tags.contains([tag.strip().lower()]))
    if query and query.strip():
        like = f"%{query.strip()[:80]}%"
        stmt = stmt.where(or_(m.Resource.title.ilike(like), m.Resource.summary.ilike(like)))
    rows = await db.scalars(stmt.order_by(m.Resource.title).limit(min(limit, MAX_LIMIT)))
    return list(rows)


async def get_resource(
    db: AsyncSession, actor: Principal, resource_id: uuid.UUID, *, faculty: bool = False
) -> m.Resource:
    row = await db.scalar(
        select(m.Resource).where(
            m.Resource.id == resource_id, *visible_resource_filters(actor, faculty=faculty)
        )
    )
    if row is None:
        raise NotFound
    return row


# ---- therapists ------------------------------------------------------------------------------


@dataclasses.dataclass
class TherapistCard:
    therapist: m.Therapist
    user: m.User
    next_available_at: dt.datetime | None
    on_my_care_team: bool


def verified_filter(now: dt.datetime) -> ColumnElement[bool]:
    """Only therapists whose professional verification is current appear to students."""
    return and_(
        m.Therapist.verification_status == VerificationStatus.VERIFIED,
        or_(
            m.Therapist.licence_expires_on.is_(None),
            m.Therapist.licence_expires_on >= now.date(),
        ),
    )


def _open_slot_filters(now: dt.datetime) -> list[ColumnElement[bool]]:
    """Availability that starts in the booking window and has no live appointment on it."""
    taken = exists().where(
        m.Appointment.availability_id == m.TherapistAvailability.id,
        m.Appointment.status.in_((AppointmentStatus.REQUESTED, AppointmentStatus.CONFIRMED)),
    )
    return [
        m.TherapistAvailability.starts_at >= now + BOOKING_LEAD_TIME,
        m.TherapistAvailability.starts_at <= now + SLOT_WINDOW,
        ~taken,
    ]


async def list_therapists(
    db: AsyncSession,
    actor: Principal,
    *,
    specialty: str | None,
    language: str | None,
    accepting_only: bool,
    limit: int,
) -> list[TherapistCard]:
    now = now_utc()
    stmt = (
        select(m.Therapist, m.User)
        .join(m.User, m.User.id == m.Therapist.user_id)
        .where(
            m.Therapist.institution_id == actor.institution_id,
            m.User.status == UserStatus.ACTIVE,
            m.User.deleted_at.is_(None),
            verified_filter(now),
        )
    )
    if specialty:
        stmt = stmt.where(m.Therapist.specialties.contains([specialty.strip()]))
    if language:
        stmt = stmt.where(m.Therapist.languages.contains([language.strip()]))
    if accepting_only:
        stmt = stmt.where(m.Therapist.accepting_new_students.is_(True))
    rows = (await db.execute(stmt.order_by(m.User.full_name).limit(min(limit, MAX_LIMIT)))).all()
    ids = [t.user_id for t, _ in rows]
    next_by: dict[uuid.UUID, dt.datetime] = {}
    linked: set[uuid.UUID] = set()
    if ids:
        for tid, first in await db.execute(
            select(
                m.TherapistAvailability.therapist_id, func.min(m.TherapistAvailability.starts_at)
            )
            .where(m.TherapistAvailability.therapist_id.in_(ids), *_open_slot_filters(now))
            .group_by(m.TherapistAvailability.therapist_id)
        ):
            next_by[tid] = first
        linked = set(
            await db.scalars(
                select(m.CareTeamMember.therapist_id).where(
                    m.CareTeamMember.student_id == actor.user_id,
                    m.CareTeamMember.therapist_id.in_(ids),
                    m.CareTeamMember.starts_at <= now,
                    or_(m.CareTeamMember.ends_at.is_(None), m.CareTeamMember.ends_at > now),
                )
            )
        )
    return [TherapistCard(t, u, next_by.get(t.user_id), t.user_id in linked) for t, u in rows]


async def get_therapist(
    db: AsyncSession, actor: Principal, therapist_id: uuid.UUID
) -> TherapistCard:
    row = (
        await db.execute(
            select(m.Therapist, m.User)
            .join(m.User, m.User.id == m.Therapist.user_id)
            .where(
                m.Therapist.user_id == therapist_id,
                m.Therapist.institution_id == actor.institution_id,
                m.User.status == UserStatus.ACTIVE,
                m.User.deleted_at.is_(None),
                verified_filter(now_utc()),
            )
        )
    ).first()
    if row is None:
        raise NotFound  # another institution's therapist looks exactly like a missing one
    therapist, user = row
    now = now_utc()
    first = await db.scalar(
        select(func.min(m.TherapistAvailability.starts_at)).where(
            m.TherapistAvailability.therapist_id == therapist_id, *_open_slot_filters(now)
        )
    )
    linked = await has_active_care_link(
        db, therapist_id=therapist_id, student_id=actor.user_id, now=now
    )
    return TherapistCard(therapist, user, first, linked)


async def open_slots(
    db: AsyncSession, actor: Principal, therapist_id: uuid.UUID
) -> list[m.TherapistAvailability]:
    await get_therapist(db, actor, therapist_id)  # same tenant, active; else NotFound
    rows = await db.scalars(
        select(m.TherapistAvailability)
        .where(
            and_(
                m.TherapistAvailability.therapist_id == therapist_id,
                m.TherapistAvailability.institution_id == actor.institution_id,
                *_open_slot_filters(now_utc()),
            )
        )
        .order_by(m.TherapistAvailability.starts_at)
        .limit(200)
    )
    return list(rows)
