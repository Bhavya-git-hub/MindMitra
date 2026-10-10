"""A therapist's appointment list: requests to answer, upcoming sessions and history.

Status changes (confirm, decline, cancel, no-show) are in ``care.update_appointment_status``;
this module only reads. A therapist sees the student's name and the reason the student wrote,
for appointments booked with them.
"""

import dataclasses
import uuid
from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.errors import InvalidInput
from app.application.therapist_access import require_verified
from app.application.timeutil import now_utc
from app.domain.auth.policies import Principal
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import AppointmentStatus

Scope = Literal["requests", "upcoming", "past", "all"]


@dataclasses.dataclass
class AppointmentRow:
    appointment: m.Appointment
    student_name: str
    session_id: uuid.UUID | None  # the delivered session, once started


async def rows_for(
    db: AsyncSession, actor: Principal, appointments: list[tuple[m.Appointment, str]]
) -> list[AppointmentRow]:
    ids = [a.id for a, _ in appointments]
    sessions: dict[uuid.UUID, uuid.UUID] = {}
    if ids:
        sessions = {
            appt_id: sid
            for appt_id, sid in await db.execute(
                select(m.TherapySession.appointment_id, m.TherapySession.id).where(
                    m.TherapySession.appointment_id.in_(ids),
                    m.TherapySession.therapist_id == actor.user_id,
                )
            )
        }
    return [AppointmentRow(a, name, sessions.get(a.id)) for a, name in appointments]


async def list_appointments(
    db: AsyncSession,
    actor: Principal,
    *,
    scope: Scope,
    status: AppointmentStatus | None = None,
    limit: int,
) -> list[AppointmentRow]:
    await require_verified(db, actor, "appointment.list")
    if not 1 <= limit <= 200:
        raise InvalidInput("limit must be between 1 and 200.")
    now = now_utc()
    stmt = (
        select(m.Appointment, m.User.full_name)
        .join(m.User, m.User.id == m.Appointment.student_id)
        .where(
            m.Appointment.therapist_id == actor.user_id,
            m.Appointment.institution_id == actor.institution_id,
        )
    )
    if status is not None:
        stmt = stmt.where(m.Appointment.status == status).order_by(m.Appointment.starts_at.desc())
    elif scope == "requests":
        stmt = stmt.where(
            m.Appointment.status == AppointmentStatus.REQUESTED, m.Appointment.ends_at >= now
        ).order_by(m.Appointment.starts_at.asc())
    elif scope == "upcoming":
        stmt = stmt.where(
            m.Appointment.status == AppointmentStatus.CONFIRMED, m.Appointment.ends_at >= now
        ).order_by(m.Appointment.starts_at.asc())
    elif scope == "past":
        stmt = stmt.where(
            or_(
                m.Appointment.ends_at < now,
                m.Appointment.status.in_(
                    (
                        AppointmentStatus.CANCELLED,
                        AppointmentStatus.COMPLETED,
                        AppointmentStatus.NO_SHOW,
                    )
                ),
            )
        ).order_by(m.Appointment.starts_at.desc())
    else:
        stmt = stmt.order_by(m.Appointment.starts_at.desc())
    rows = (await db.execute(stmt.limit(limit))).all()
    return await rows_for(db, actor, [(a, name) for a, name in rows])
