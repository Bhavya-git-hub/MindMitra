"""Appointment reminders, sent by the scheduler at the hours each institution chose.

For a confirmed appointment, a reminder is due once the time is within one of the configured
offsets (for example 24 and 2 hours before). Each (appointment, time, offset) is recorded in
``notify.appointment_reminders`` so a reminder is never sent twice, even with several scheduler
processes. When the scheduler first sees an appointment after more than one offset has passed
(it was confirmed late), it sends one reminder, not one per offset. Moving an appointment
changes its time, so the new time gets its own reminders.

Both the student and the therapist are reminded. The reminder says only that an appointment
is coming up; the app shows when and with whom.
"""

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application import institution_settings
from app.application.notifications import notify
from app.application.timeutil import now_utc
from app.domain.settings import MAX_REMINDERS
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import AppointmentStatus, NotificationType

LOOKAHEAD = dt.timedelta(hours=168)  # the largest offset an institution can choose


async def _due_offsets(
    db: AsyncSession, appt: m.Appointment, offsets: list[int], now: dt.datetime
) -> list[int]:
    """Offsets whose time has come and that were not recorded yet for this start time."""
    passed = [h for h in offsets if appt.starts_at - dt.timedelta(hours=h) <= now]
    if not passed:
        return []
    done = set(
        await db.scalars(
            select(m.AppointmentReminder.offset_hours).where(
                m.AppointmentReminder.appointment_id == appt.id,
                m.AppointmentReminder.starts_at == appt.starts_at,
            )
        )
    )
    return [h for h in passed if h not in done]


async def send_due_reminders(
    session_factory: async_sessionmaker[AsyncSession], *, now: dt.datetime | None = None
) -> int:
    """Returns how many appointments were reminded."""
    now = now or now_utc()
    reminded = 0
    async with session_factory() as db:
        appts = list(
            await db.scalars(
                select(m.Appointment)
                .where(
                    m.Appointment.status == AppointmentStatus.CONFIRMED,
                    m.Appointment.starts_at > now,
                    m.Appointment.starts_at <= now + LOOKAHEAD,
                )
                .order_by(m.Appointment.starts_at)
            )
        )
        settings_cache: dict[uuid.UUID, list[int]] = {}
        for appt in appts:
            if appt.institution_id not in settings_cache:
                config = (await institution_settings.load(db, appt.institution_id)).notifications
                hours = config.appointment_reminder_hours[:MAX_REMINDERS]
                settings_cache[appt.institution_id] = hours if config.reminders_enabled else []
            due = await _due_offsets(db, appt, settings_cache[appt.institution_id], now)
            if not due:
                continue
            # Claim every due offset at once; a concurrent scheduler that got there first wins
            # and this one sends nothing for the offsets it lost.
            claimed = list(
                await db.scalars(
                    pg_insert(m.AppointmentReminder)
                    .values(
                        [
                            {
                                "institution_id": appt.institution_id,
                                "appointment_id": appt.id,
                                "starts_at": appt.starts_at,
                                "offset_hours": h,
                            }
                            for h in due
                        ]
                    )
                    .on_conflict_do_nothing(constraint="uq_appointment_reminders_once")
                    .returning(m.AppointmentReminder.offset_hours)
                )
            )
            if not claimed:
                continue
            for user_id in (appt.student_id, appt.therapist_id):
                await notify(
                    db,
                    institution_id=appt.institution_id,
                    user_id=user_id,
                    type=NotificationType.APPOINTMENT_REMINDER,
                    title="You have an appointment coming up",
                    payload={"appointment_id": appt.id, "event": "reminder"},
                )
            reminded += 1
        await db.commit()
    return reminded
