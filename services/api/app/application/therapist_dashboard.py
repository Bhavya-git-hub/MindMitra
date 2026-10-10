"""The therapist's home page: what needs attention today, in one round trip.

Counts only, plus the next few appointments. Nothing here exposes wellbeing data or notes, so
it is available to any signed-in therapist; an unverified therapist sees their verification
status and an empty workload (they cannot be given students until verified).
"""

import dataclasses
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.risk_alerts import OPEN_STATUSES
from app.application.therapist_access import (
    active_students,
    effective_verification,
    own_therapist,
)
from app.application.therapist_appointments import AppointmentRow, rows_for
from app.application.timeutil import day_bounds, local_today, now_utc
from app.domain.auth.policies import Principal
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import (
    AlertSeverity,
    AlertStatus,
    AppointmentStatus,
    FollowUpStatus,
)


@dataclasses.dataclass
class Dashboard:
    therapist: m.Therapist
    verification: str
    today: list[AppointmentRow]
    next_appointment: AppointmentRow | None
    pending_requests: int
    alerts_by_severity: dict[str, int]
    alerts_overdue: int
    follow_ups_due_today: int
    follow_ups_overdue: int
    unread_messages: int
    caseload: int


async def build(db: AsyncSession, actor: Principal, zone: ZoneInfo) -> Dashboard:
    therapist = await own_therapist(db, actor)
    verification = effective_verification(therapist)
    empty = Dashboard(
        therapist=therapist,
        verification=verification,
        today=[],
        next_appointment=None,
        pending_requests=0,
        alerts_by_severity={s.value: 0 for s in AlertSeverity},
        alerts_overdue=0,
        follow_ups_due_today=0,
        follow_ups_overdue=0,
        unread_messages=0,
        caseload=0,
    )
    if verification != "verified":
        return empty

    now = now_utc()
    today = local_today(zone, now)
    start, end = day_bounds(today, zone)
    live = (AppointmentStatus.REQUESTED, AppointmentStatus.CONFIRMED)

    def mine() -> list:  # type: ignore[type-arg]
        return [
            m.Appointment.therapist_id == actor.user_id,
            m.Appointment.institution_id == actor.institution_id,
        ]

    todays = (
        await db.execute(
            select(m.Appointment, m.User.full_name)
            .join(m.User, m.User.id == m.Appointment.student_id)
            .where(
                *mine(),
                m.Appointment.status.in_(live),
                m.Appointment.starts_at >= start,
                m.Appointment.starts_at < end,
            )
            .order_by(m.Appointment.starts_at)
        )
    ).all()
    nxt = (
        await db.execute(
            select(m.Appointment, m.User.full_name)
            .join(m.User, m.User.id == m.Appointment.student_id)
            .where(
                *mine(),
                m.Appointment.status == AppointmentStatus.CONFIRMED,
                m.Appointment.ends_at >= now,
            )
            .order_by(m.Appointment.starts_at)
            .limit(1)
        )
    ).first()
    pending = int(
        await db.scalar(
            select(func.count())
            .select_from(m.Appointment)
            .where(
                *mine(),
                m.Appointment.status == AppointmentStatus.REQUESTED,
                m.Appointment.ends_at >= now,
            )
        )
        or 0
    )

    visible_alert = (
        m.RiskAlert.institution_id == actor.institution_id,
        m.RiskAlert.status.in_(OPEN_STATUSES),
        (m.RiskAlert.assigned_to == actor.user_id)
        | (m.RiskAlert.assigned_to.is_(None) & m.RiskAlert.student_id.in_(active_students(actor))),
    )
    by_severity = {s.value: 0 for s in AlertSeverity}
    for severity, n in await db.execute(
        select(m.RiskAlert.severity, func.count())
        .where(*visible_alert)
        .group_by(m.RiskAlert.severity)
    ):
        by_severity[severity.value] = n
    overdue_alerts = int(
        await db.scalar(
            select(func.count())
            .select_from(m.RiskAlert)
            .where(
                *visible_alert,
                m.RiskAlert.status.in_((AlertStatus.OPEN, AlertStatus.ESCALATED)),
                m.RiskAlert.sla_ack_due_at < now,
            )
        )
        or 0
    )

    open_follow = (
        m.FollowUp.therapist_id == actor.user_id,
        m.FollowUp.status == FollowUpStatus.OPEN,
        m.FollowUp.student_id.in_(active_students(actor)),
    )
    due_today = int(
        await db.scalar(
            select(func.count())
            .select_from(m.FollowUp)
            .where(*open_follow, m.FollowUp.due_on == today)
        )
        or 0
    )
    overdue_follow = int(
        await db.scalar(
            select(func.count())
            .select_from(m.FollowUp)
            .where(*open_follow, m.FollowUp.due_on < today)
        )
        or 0
    )
    unread = int(
        await db.scalar(
            select(func.count())
            .select_from(m.Message)
            .where(
                m.Message.therapist_id == actor.user_id,
                m.Message.institution_id == actor.institution_id,
                m.Message.sender_id != actor.user_id,
                m.Message.read_at.is_(None),
            )
        )
        or 0
    )
    caseload = int(
        await db.scalar(select(func.count()).select_from(active_students(actor).subquery())) or 0
    )

    rows = await rows_for(
        db, actor, [(a, n) for a, n in todays] + ([(nxt[0], nxt[1])] if nxt else [])
    )
    today_rows = rows[: len(todays)]
    next_row = rows[len(todays)] if nxt else None
    return Dashboard(
        therapist=therapist,
        verification=verification,
        today=today_rows,
        next_appointment=next_row,
        pending_requests=pending,
        alerts_by_severity=by_severity,
        alerts_overdue=overdue_alerts,
        follow_ups_due_today=due_today,
        follow_ups_overdue=overdue_follow,
        unread_messages=unread,
        caseload=caseload,
    )
