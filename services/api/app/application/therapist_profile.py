"""A therapist's own profile, professional verification and availability."""

import dataclasses
import datetime as dt
import uuid

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.access import NotFound, enforce
from app.application.auth.errors import Conflict
from app.application.errors import InvalidInput
from app.application.therapist_access import own_therapist
from app.application.timeutil import now_utc
from app.domain.auth.policies import (
    Principal,
    can_manage_own_therapist_record,
    can_verify_therapist,
)
from app.infrastructure.db import models as m
from app.infrastructure.db.audit import append_audit_event
from app.infrastructure.db.enums import (
    AppointmentStatus,
    AuditOutcome,
    SessionMode,
    UserRole,
    VerificationStatus,
)
from app.infrastructure.db.ids import uuid7

MAX_BIO = 2000
MAX_TAGS = 8
MAX_SLOT_MINUTES = 240
MIN_SLOT_MINUTES = 15
MAX_REPEAT_WEEKS = 11
HORIZON = dt.timedelta(days=120)
LIVE = (AppointmentStatus.REQUESTED, AppointmentStatus.CONFIRMED)


def _tags(values: list[str], label: str, length: int) -> list[str]:
    out: list[str] = []
    for raw in values:
        value = " ".join(raw.split())
        if not value:
            continue
        if len(value) > length:
            raise InvalidInput(f"Each {label} can be up to {length} characters.")
        if value.lower() not in {v.lower() for v in out}:
            out.append(value)
    if len(out) > MAX_TAGS:
        raise InvalidInput(f"Please list at most {MAX_TAGS} {label}s.")
    return out


async def _audit(db: AsyncSession, actor: Principal, action: str, **details: object) -> None:
    await append_audit_event(
        db,
        institution_id=actor.institution_id,
        actor_id=actor.user_id,
        actor_role=UserRole(actor.role.value),
        action=action,
        outcome=AuditOutcome.ALLOWED,
        resource_type="therapist",
        resource_id=actor.user_id,
        details=dict(details),
    )


# ---- profile ----------------------------------------------------------------------------------


async def get_profile(db: AsyncSession, actor: Principal) -> tuple[m.Therapist, m.User]:
    therapist = await own_therapist(db, actor)
    user = await db.get(m.User, actor.user_id)
    assert user is not None
    return therapist, user


async def update_profile(
    db: AsyncSession,
    actor: Principal,
    *,
    bio: str | None,
    specialties: list[str] | None,
    languages: list[str] | None,
    accepting_new_students: bool | None,
    max_caseload: int | None,
) -> tuple[m.Therapist, m.User]:
    therapist, user = await get_profile(db, actor)
    enforce(
        can_manage_own_therapist_record(
            actor, institution_id=therapist.institution_id, therapist_id=therapist.user_id
        ),
        action="therapist_profile.update",
        resource_type="therapist",
        resource_id=therapist.user_id,
    )
    changed: list[str] = []
    if bio is not None:
        text = bio.strip()
        if len(text) > MAX_BIO:
            raise InvalidInput(f"Your bio can be up to {MAX_BIO} characters.")
        therapist.bio = text or None
        changed.append("bio")
    if specialties is not None:
        therapist.specialties = _tags(specialties, "focus area", 80)
        changed.append("specialties")
    if languages is not None:
        therapist.languages = _tags(languages, "language", 40)
        changed.append("languages")
    if accepting_new_students is not None:
        therapist.accepting_new_students = accepting_new_students
        changed.append("accepting_new_students")
    if max_caseload is not None:
        if not 1 <= max_caseload <= 500:
            raise InvalidInput("Caseload must be between 1 and 500.")
        therapist.max_caseload = max_caseload
        changed.append("max_caseload")
    await _audit(db, actor, "therapist_profile.update", fields=changed)
    await db.commit()
    return therapist, user


async def submit_verification(
    db: AsyncSession,
    actor: Principal,
    *,
    licence_number: str,
    licence_body: str | None,
    licence_expires_on: dt.date | None,
) -> m.Therapist:
    """Send licence details for (re-)verification. Always goes back to ``pending``: nobody
    verifies themselves."""
    therapist = await own_therapist(db, actor)
    number = " ".join(licence_number.split())
    if not 3 <= len(number) <= 60:
        raise InvalidInput("Please enter your licence or registration number.")
    if licence_expires_on is not None and licence_expires_on < now_utc().date():
        raise InvalidInput("That licence has already expired.")
    therapist.licence_number = number
    therapist.licence_body = (licence_body or "").strip()[:120] or None
    therapist.licence_expires_on = licence_expires_on
    therapist.verification_status = VerificationStatus.PENDING
    therapist.verified_at = None
    therapist.verified_by = None
    therapist.verification_note = None
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError as exc:
        raise Conflict("That licence number is already registered at your institution.") from exc
    await _audit(db, actor, "therapist_verification.submit")
    await db.commit()
    return therapist


# ---- administrators verify ---------------------------------------------------------------------


async def list_for_verification(
    db: AsyncSession, actor: Principal, status: VerificationStatus | None
) -> list[tuple[m.Therapist, m.User]]:
    stmt = (
        select(m.Therapist, m.User)
        .join(m.User, m.User.id == m.Therapist.user_id)
        .where(m.Therapist.institution_id == actor.institution_id, m.User.deleted_at.is_(None))
        .order_by(m.Therapist.verification_status, m.User.full_name)
    )
    if status is not None:
        stmt = stmt.where(m.Therapist.verification_status == status)
    return [(t, u) for t, u in (await db.execute(stmt.limit(200))).all()]


async def set_verification(
    db: AsyncSession,
    actor: Principal,
    therapist_id: uuid.UUID,
    *,
    status: VerificationStatus,
    note: str | None,
    licence_expires_on: dt.date | None,
) -> tuple[m.Therapist, m.User]:
    therapist = await db.get(m.Therapist, therapist_id)
    if therapist is None or therapist.institution_id != actor.institution_id:
        raise NotFound
    enforce(
        can_verify_therapist(
            actor,
            therapist_institution_id=therapist.institution_id,
            therapist_id=therapist.user_id,
        ),
        action="therapist.verify",
        resource_type="therapist",
        resource_id=therapist_id,
    )
    clean_note = (note or "").strip()
    if len(clean_note) > 300:
        raise InvalidInput("Please keep the note under 300 characters.")
    if status is VerificationStatus.VERIFIED:
        expiry = licence_expires_on or therapist.licence_expires_on
        if expiry is not None and expiry < now_utc().date():
            raise InvalidInput("The licence has already expired.")
        therapist.licence_expires_on = expiry
        therapist.verified_at = now_utc()
        therapist.verified_by = actor.user_id
    else:
        therapist.verified_at = None
        therapist.verified_by = None
    therapist.verification_status = status
    therapist.verification_note = clean_note or None
    await append_audit_event(
        db,
        institution_id=actor.institution_id,
        actor_id=actor.user_id,
        actor_role=UserRole.ADMINISTRATOR,
        action="therapist.verify",
        outcome=AuditOutcome.ALLOWED,
        resource_type="therapist",
        resource_id=therapist_id,
        details={"status": status.value},
    )
    await db.commit()
    user = await db.get(m.User, therapist_id)
    assert user is not None
    return therapist, user


# ---- availability -----------------------------------------------------------------------------


@dataclasses.dataclass
class SlotView:
    slot: m.TherapistAvailability
    appointment_id: uuid.UUID | None  # the live appointment on this slot, if any
    appointment_status: AppointmentStatus | None


async def list_availability(
    db: AsyncSession, actor: Principal, *, start: dt.datetime, end: dt.datetime
) -> list[SlotView]:
    rows = await db.execute(
        select(m.TherapistAvailability, m.Appointment.id, m.Appointment.status)
        .outerjoin(
            m.Appointment,
            and_(
                m.Appointment.availability_id == m.TherapistAvailability.id,
                m.Appointment.status.in_(LIVE),
            ),
        )
        .where(
            m.TherapistAvailability.therapist_id == actor.user_id,
            m.TherapistAvailability.institution_id == actor.institution_id,
            m.TherapistAvailability.starts_at >= start,
            m.TherapistAvailability.starts_at < end,
        )
        .order_by(m.TherapistAvailability.starts_at)
        .limit(500)
    )
    return [SlotView(s, aid, st) for s, aid, st in rows.all()]


async def add_availability(
    db: AsyncSession,
    actor: Principal,
    *,
    starts_at: dt.datetime,
    ends_at: dt.datetime,
    mode: SessionMode,
    repeat_weeks: int,
) -> list[m.TherapistAvailability]:
    """One slot, or the same slot repeated weekly. All or nothing: if any copy overlaps
    existing availability, none are saved."""
    therapist = await own_therapist(db, actor)
    enforce(
        can_manage_own_therapist_record(
            actor, institution_id=therapist.institution_id, therapist_id=therapist.user_id
        ),
        action="availability.create",
        resource_type="availability",
    )
    if starts_at.tzinfo is None or ends_at.tzinfo is None:
        raise InvalidInput("Please include a time zone with the times.")
    minutes = (ends_at - starts_at).total_seconds() / 60
    if not MIN_SLOT_MINUTES <= minutes <= MAX_SLOT_MINUTES:
        raise InvalidInput(
            f"A slot must last between {MIN_SLOT_MINUTES} and {MAX_SLOT_MINUTES} minutes."
        )
    now = now_utc()
    if starts_at <= now:
        raise InvalidInput("Slots must start in the future.")
    if not 0 <= repeat_weeks <= MAX_REPEAT_WEEKS:
        raise InvalidInput(f"Repeat for at most {MAX_REPEAT_WEEKS} more weeks.")
    last_start = starts_at + dt.timedelta(weeks=repeat_weeks)
    if last_start > now + HORIZON:
        raise InvalidInput("Please add availability up to about four months ahead.")

    created: list[m.TherapistAvailability] = []
    try:
        async with db.begin_nested():
            for week in range(repeat_weeks + 1):
                delta = dt.timedelta(weeks=week)
                slot = m.TherapistAvailability(
                    id=uuid7(),
                    institution_id=actor.institution_id,
                    therapist_id=actor.user_id,
                    starts_at=starts_at + delta,
                    ends_at=ends_at + delta,
                    mode=mode,
                )
                db.add(slot)
                created.append(slot)
            await db.flush()
    except IntegrityError as exc:
        raise Conflict("That time overlaps availability you have already added.") from exc
    await _audit(db, actor, "availability.create", count=len(created))
    await db.commit()
    return created


async def remove_availability(db: AsyncSession, actor: Principal, slot_id: uuid.UUID) -> None:
    slot = await db.get(m.TherapistAvailability, slot_id)
    if slot is None:
        raise NotFound
    enforce(
        can_manage_own_therapist_record(
            actor, institution_id=slot.institution_id, therapist_id=slot.therapist_id
        ),
        action="availability.delete",
        resource_type="availability",
        resource_id=slot_id,
    )
    live = await db.scalar(
        select(m.Appointment.id).where(
            m.Appointment.availability_id == slot_id, m.Appointment.status.in_(LIVE)
        )
    )
    if live is not None:
        raise Conflict("A student has requested or booked this time. Decline or cancel it first.")
    used = await db.scalar(
        select(m.Appointment.id).where(m.Appointment.availability_id == slot_id).limit(1)
    )
    if used is not None:
        raise Conflict("This time has appointment history, so it can't be removed.")
    await db.delete(slot)
    await _audit(db, actor, "availability.delete")
    await db.commit()
