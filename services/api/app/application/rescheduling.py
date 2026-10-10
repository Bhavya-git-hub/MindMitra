"""Moving an appointment to another of the same therapist's open times.

Either person in the appointment can move it, up to ``MAX_RESCHEDULES`` times, while it has not
started. The row is updated in place, so its history, messages and reminders stay attached; the
old time is freed in the same statement, and the database's exclusion constraints still refuse
a time the therapist or the student already has booked.

- When the **student** moves it, it goes back to *requested*: the therapist confirms again.
- When the **therapist** moves it, it keeps its status. The student is told, and can move it
  again or cancel if the new time does not suit them.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.access import NotFound, enforce
from app.application.appointment_events import appointment_changed
from app.application.auth.errors import Conflict
from app.application.booking import LIVE, MAX_RESCHEDULES, AppointmentView
from app.application.directory import BOOKING_LEAD_TIME
from app.application.errors import InvalidInput
from app.application.notifications import notify
from app.application.therapist_access import require_verified
from app.application.timeutil import now_utc
from app.domain.auth.permissions import Role
from app.domain.auth.policies import (
    Principal,
    can_cancel_appointment_as_student,
    can_manage_appointment,
)
from app.infrastructure.db import models as m
from app.infrastructure.db.audit import append_audit_event
from app.infrastructure.db.enums import (
    AppointmentStatus,
    AuditOutcome,
    NotificationType,
    UserRole,
)


async def reschedule(
    db: AsyncSession, actor: Principal, appointment_id: uuid.UUID, availability_id: uuid.UUID
) -> AppointmentView:
    by_student = actor.role is Role.STUDENT
    if not by_student:
        await require_verified(db, actor, "appointment.reschedule")
    appt = await db.get(m.Appointment, appointment_id, with_for_update=True)
    if appt is None:
        raise NotFound
    decision = (
        can_cancel_appointment_as_student(
            actor, appointment_institution_id=appt.institution_id, student_id=appt.student_id
        )
        if by_student
        else can_manage_appointment(
            actor, appointment_institution_id=appt.institution_id, therapist_id=appt.therapist_id
        )
    )
    enforce(
        decision,
        action="appointment.reschedule",
        resource_type="appointment",
        resource_id=appt.id,
        subject_student_id=appt.student_id,
    )
    now = now_utc()
    if appt.status not in LIVE:
        raise Conflict("Only a requested or confirmed appointment can be moved.")
    if appt.starts_at <= now:
        raise Conflict("This appointment has already started or passed.")
    if appt.reschedule_count >= MAX_RESCHEDULES:
        raise Conflict(
            f"This appointment has been moved {MAX_RESCHEDULES} times. "
            "Please cancel it and book a new one."
        )
    slot = await db.get(m.TherapistAvailability, availability_id, with_for_update=True)
    # Only the same therapist's times, in the same institution; anything else looks missing.
    if (
        slot is None
        or slot.institution_id != appt.institution_id
        or slot.therapist_id != appt.therapist_id
    ):
        raise NotFound
    if slot.id == appt.availability_id:
        raise InvalidInput("That is the time it is already booked for.")
    if slot.starts_at < now + BOOKING_LEAD_TIME:
        raise InvalidInput("That time is too soon. Please pick a later one.")

    appt.availability_id = slot.id
    appt.starts_at = slot.starts_at
    appt.ends_at = slot.ends_at
    appt.mode = slot.mode
    appt.rescheduled_at = now
    appt.reschedule_count += 1
    if by_student:
        appt.status = AppointmentStatus.REQUESTED
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError as exc:
        message = str(exc.orig)
        if "ex_appointments_student_no_overlap" in message:
            raise Conflict(
                "You already have an appointment at that time."
                if by_student
                else "The student already has another appointment at that time."
            ) from exc
        raise Conflict("Sorry, that time has just been taken. Please choose another.") from exc

    event = "rescheduled_by_student" if by_student else "rescheduled_by_therapist"
    await notify(
        db,
        institution_id=appt.institution_id,
        user_id=appt.therapist_id if by_student else appt.student_id,
        type=NotificationType.APPOINTMENT_UPDATE,
        title=(
            "A student asked to move their appointment"
            if by_student
            else "Your therapist moved your appointment"
        ),
        payload={"appointment_id": appt.id, "event": event},
    )
    appointment_changed(db, appt, event)
    await append_audit_event(
        db,
        institution_id=actor.institution_id,
        actor_id=actor.user_id,
        actor_role=UserRole.STUDENT if by_student else UserRole.THERAPIST,
        action="appointment.reschedule",
        outcome=AuditOutcome.ALLOWED,
        resource_type="appointment",
        resource_id=appt.id,
        subject_student_id=appt.student_id,
        details={"count": str(appt.reschedule_count), "status": appt.status.value},
    )
    other = appt.therapist_id if by_student else appt.student_id
    name = await db.scalar(select(m.User.full_name).where(m.User.id == other)) or ""
    await db.commit()
    return AppointmentView(appt, name)
