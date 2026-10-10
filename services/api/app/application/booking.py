"""Booking and cancelling therapy appointments as a student, and listing one's own."""

import dataclasses
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.access import NotFound, enforce, has_active_care_link
from app.application.auth.errors import Conflict
from app.application.directory import BOOKING_LEAD_TIME
from app.application.errors import InvalidInput
from app.application.timeutil import now_utc
from app.domain.auth.policies import (
    Principal,
    can_book_with_therapist,
    can_cancel_appointment_as_student,
)
from app.infrastructure.db import models as m
from app.infrastructure.db.audit import append_audit_event
from app.infrastructure.db.enums import (
    AppointmentStatus,
    AuditOutcome,
    NotificationType,
    UserRole,
    UserStatus,
)
from app.infrastructure.db.ids import uuid7

MAX_UPCOMING_APPOINTMENTS = 3
MAX_REASON_LENGTH = 1000
LIVE = (AppointmentStatus.REQUESTED, AppointmentStatus.CONFIRMED)


@dataclasses.dataclass
class AppointmentView:
    appointment: m.Appointment
    therapist_name: str

    @property
    def can_cancel(self) -> bool:
        a = self.appointment
        return a.status in LIVE and a.starts_at > now_utc()


async def list_own(
    db: AsyncSession, actor: Principal, *, upcoming: bool | None, limit: int
) -> list[AppointmentView]:
    stmt = (
        select(m.Appointment, m.User.full_name)
        .join(m.User, m.User.id == m.Appointment.therapist_id)
        .where(
            m.Appointment.student_id == actor.user_id,
            m.Appointment.institution_id == actor.institution_id,
        )
    )
    now = now_utc()
    if upcoming is True:
        stmt = stmt.where(m.Appointment.starts_at >= now, m.Appointment.status.in_(LIVE)).order_by(
            m.Appointment.starts_at.asc()
        )
    else:
        if upcoming is False:
            stmt = stmt.where(m.Appointment.starts_at < now)
        stmt = stmt.order_by(m.Appointment.starts_at.desc())
    rows = await db.execute(stmt.limit(min(limit, 200)))
    return [AppointmentView(a, name) for a, name in rows.all()]


async def next_upcoming(db: AsyncSession, actor: Principal) -> AppointmentView | None:
    rows = await list_own(db, actor, upcoming=True, limit=1)
    return rows[0] if rows else None


async def _notify(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    user_id: uuid.UUID,
    title: str,
    appointment_id: uuid.UUID,
    event: str,
) -> None:
    # Identifiers only: no names, times or reasons (notify schema rules).
    db.add(
        m.Notification(
            id=uuid7(),
            institution_id=institution_id,
            user_id=user_id,
            type=NotificationType.APPOINTMENT_UPDATE,
            title=title,
            payload={"appointment_id": str(appointment_id), "event": event},
        )
    )


async def book(
    db: AsyncSession, actor: Principal, availability_id: uuid.UUID, reason: str | None
) -> AppointmentView:
    slot = await db.get(m.TherapistAvailability, availability_id, with_for_update=True)
    if slot is None or slot.institution_id != actor.institution_id:
        raise NotFound
    therapist = await db.get(m.Therapist, slot.therapist_id)
    therapist_user = await db.get(m.User, slot.therapist_id)
    if (
        therapist is None
        or therapist_user is None
        or therapist_user.status is not UserStatus.ACTIVE
        or therapist_user.deleted_at is not None
    ):
        raise NotFound
    now = now_utc()
    linked = await has_active_care_link(
        db, therapist_id=therapist.user_id, student_id=actor.user_id, now=now
    )
    enforce(
        can_book_with_therapist(
            actor,
            therapist_institution_id=therapist.institution_id,
            accepting_new_students=therapist.accepting_new_students,
            has_active_care_link=linked,
        ),
        action="appointment.create",
        resource_type="appointment",
        subject_student_id=actor.user_id,
    )
    if slot.starts_at < now + BOOKING_LEAD_TIME:
        raise InvalidInput("That time is too soon to book. Please pick a later slot.")
    cleaned_reason = (reason or "").strip() or None
    if cleaned_reason and len(cleaned_reason) > MAX_REASON_LENGTH:
        raise InvalidInput(f"Please keep the note under {MAX_REASON_LENGTH} characters.")

    upcoming = await db.scalar(
        select(func.count())
        .select_from(m.Appointment)
        .where(
            m.Appointment.student_id == actor.user_id,
            m.Appointment.institution_id == actor.institution_id,
            m.Appointment.status.in_(LIVE),
            m.Appointment.starts_at >= now,
        )
    )
    if (upcoming or 0) >= MAX_UPCOMING_APPOINTMENTS:
        raise Conflict(
            f"You already have {MAX_UPCOMING_APPOINTMENTS} upcoming appointments. "
            "Cancel one before booking another."
        )

    appt = m.Appointment(
        id=uuid7(),
        institution_id=actor.institution_id,
        student_id=actor.user_id,
        therapist_id=therapist.user_id,
        availability_id=slot.id,
        starts_at=slot.starts_at,
        ends_at=slot.ends_at,
        mode=slot.mode,
        status=AppointmentStatus.REQUESTED,
        reason=cleaned_reason,
    )
    db.add(appt)
    try:
        # The savepoint keeps the slot lock and the rest of the request alive on a conflict.
        async with db.begin_nested():
            await db.flush()
    except IntegrityError as exc:
        message = str(exc.orig)
        if "ex_appointments_student_no_overlap" in message:
            raise Conflict("You already have an appointment at that time.") from exc
        raise Conflict("Sorry, that slot has just been taken. Please choose another.") from exc

    await _notify(
        db,
        institution_id=actor.institution_id,
        user_id=therapist.user_id,
        title="New appointment request",
        appointment_id=appt.id,
        event="requested",
    )
    await append_audit_event(
        db,
        institution_id=actor.institution_id,
        actor_id=actor.user_id,
        actor_role=UserRole.STUDENT,
        action="appointment.create",
        outcome=AuditOutcome.ALLOWED,
        resource_type="appointment",
        resource_id=appt.id,
        subject_student_id=actor.user_id,
    )
    await db.commit()
    return AppointmentView(appt, therapist_user.full_name)


async def cancel(db: AsyncSession, actor: Principal, appointment_id: uuid.UUID) -> AppointmentView:
    appt = await db.get(m.Appointment, appointment_id, with_for_update=True)
    if appt is None:
        raise NotFound
    enforce(
        can_cancel_appointment_as_student(
            actor, appointment_institution_id=appt.institution_id, student_id=appt.student_id
        ),
        action="appointment.cancel",
        resource_type="appointment",
        resource_id=appt.id,
        subject_student_id=appt.student_id,
    )
    if appt.status not in LIVE:
        raise Conflict("This appointment can no longer be cancelled.")
    now = now_utc()
    if appt.starts_at <= now:
        raise Conflict("This appointment has already started or passed.")
    appt.status = AppointmentStatus.CANCELLED
    appt.cancelled_at = now
    appt.cancelled_by = actor.user_id
    await _notify(
        db,
        institution_id=actor.institution_id,
        user_id=appt.therapist_id,
        title="Appointment cancelled",
        appointment_id=appt.id,
        event="cancelled_by_student",
    )
    await append_audit_event(
        db,
        institution_id=actor.institution_id,
        actor_id=actor.user_id,
        actor_role=UserRole.STUDENT,
        action="appointment.cancel",
        outcome=AuditOutcome.ALLOWED,
        resource_type="appointment",
        resource_id=appt.id,
        subject_student_id=actor.user_id,
    )
    name = await db.scalar(select(m.User.full_name).where(m.User.id == appt.therapist_id)) or ""
    await db.commit()
    return AppointmentView(appt, name)
