"""Support alerts for the therapist who is looking after the student.

An alert means "a person should reach out", never a conclusion about the student. A therapist
sees an alert assigned to them, or an unassigned one: a student with no care-team therapist
belongs to the whole counselling team, and whoever acknowledges the alert takes it.
Alerts are not consent-gated (the student asked for help, or a safety rule fired), but every
list and every action is audited, without the excerpt text.
"""

import dataclasses
import uuid

from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.access import NotFound, enforce, has_active_care_link
from app.application.errors import InvalidInput
from app.application.therapist_access import require_verified
from app.application.timeutil import now_utc
from app.domain.auth.policies import Principal, can_handle_risk_alert
from app.infrastructure.db import models as m
from app.infrastructure.db.audit import append_audit_event
from app.infrastructure.db.enums import AlertSeverity, AlertStatus, AuditOutcome, UserRole

OPEN_STATUSES = (
    AlertStatus.OPEN,
    AlertStatus.ACKNOWLEDGED,
    AlertStatus.ESCALATED,
    AlertStatus.IN_PROGRESS,
)
CLOSED_STATUSES = (AlertStatus.RESOLVED, AlertStatus.DISMISSED)
OUTCOMES = (
    "contacted_student",
    "session_booked",
    "referred_elsewhere",
    "emergency_services",
    "no_action_needed",
)
ACTIONS = ("acknowledge", "start", "resolve")


@dataclasses.dataclass
class AlertView:
    alert: m.RiskAlert
    student_name: str
    assigned_to_me: bool
    overdue: bool


def _view(alert: m.RiskAlert, name: str, actor: Principal) -> AlertView:
    overdue = bool(
        alert.status in (AlertStatus.OPEN, AlertStatus.ESCALATED)
        and alert.sla_ack_due_at is not None
        and alert.sla_ack_due_at < now_utc()
    )
    return AlertView(alert, name, alert.assigned_to == actor.user_id, overdue)


async def list_alerts(
    db: AsyncSession, actor: Principal, *, closed: bool, limit: int
) -> list[AlertView]:
    await require_verified(db, actor, "risk_alert.list")
    statuses = CLOSED_STATUSES if closed else OPEN_STATUSES
    severity_rank = case(
        (m.RiskAlert.severity == AlertSeverity.IMMINENT, 0),
        (m.RiskAlert.severity == AlertSeverity.HIGH, 1),
        (m.RiskAlert.severity == AlertSeverity.MODERATE, 2),
        else_=3,
    )
    rows = (
        await db.execute(
            select(m.RiskAlert, m.User.full_name)
            .join(m.User, m.User.id == m.RiskAlert.student_id)
            .where(
                m.RiskAlert.institution_id == actor.institution_id,
                m.RiskAlert.status.in_(statuses),
                # Unassigned alerts (no care-team therapist) are the counselling team's.
                or_(m.RiskAlert.assigned_to == actor.user_id, m.RiskAlert.assigned_to.is_(None)),
            )
            .order_by(
                severity_rank,
                m.RiskAlert.sla_ack_due_at.asc().nulls_last(),
                m.RiskAlert.created_at.desc(),
            )
            .limit(min(limit, 200))
        )
    ).all()
    await append_audit_event(
        db,
        institution_id=actor.institution_id,
        actor_id=actor.user_id,
        actor_role=UserRole.THERAPIST,
        action="risk_alert.list",
        outcome=AuditOutcome.ALLOWED,
        resource_type="risk_alert",
        details={"count": len(rows), "closed": closed},
    )
    await db.commit()
    return [_view(a, name, actor) for a, name in rows]


async def act_on_alert(
    db: AsyncSession,
    actor: Principal,
    alert_id: uuid.UUID,
    action: str,
    outcome: str | None,
) -> AlertView:
    await require_verified(db, actor, "risk_alert.update")
    alert = await db.get(m.RiskAlert, alert_id, with_for_update=True)
    if alert is None:
        raise NotFound
    linked = await has_active_care_link(
        db, therapist_id=actor.user_id, student_id=alert.student_id, now=now_utc()
    )
    enforce(
        can_handle_risk_alert(
            actor,
            alert_institution_id=alert.institution_id,
            assigned_to=alert.assigned_to,
            has_active_care_link=linked,
        ),
        action="risk_alert.update",
        resource_type="risk_alert",
        resource_id=alert.id,
        subject_student_id=alert.student_id,
    )
    if action not in ACTIONS:
        raise InvalidInput("Unknown action.")
    old = alert.status
    now = now_utc()
    if action == "acknowledge":
        if alert.status not in (AlertStatus.OPEN, AlertStatus.ESCALATED):
            raise InvalidInput("This alert has already been acknowledged.")
        alert.status = AlertStatus.ACKNOWLEDGED
        alert.acknowledged_at = now
        if alert.assigned_to is None:
            alert.assigned_to = actor.user_id
    elif action == "start":
        if alert.status is not AlertStatus.ACKNOWLEDGED:
            raise InvalidInput("Acknowledge the alert before starting work on it.")
        alert.status = AlertStatus.IN_PROGRESS
    else:
        if alert.status not in (AlertStatus.ACKNOWLEDGED, AlertStatus.IN_PROGRESS):
            raise InvalidInput("Acknowledge the alert before resolving it.")
        if outcome not in OUTCOMES:
            raise InvalidInput("Please say how this was resolved.")
        alert.status = AlertStatus.RESOLVED
        alert.resolved_at = now
        alert.outcome = outcome
    await append_audit_event(
        db,
        institution_id=actor.institution_id,
        actor_id=actor.user_id,
        actor_role=UserRole.THERAPIST,
        action="risk_alert.update",
        outcome=AuditOutcome.ALLOWED,
        resource_type="risk_alert",
        resource_id=alert.id,
        subject_student_id=alert.student_id,
        details={"from": old.value, "to": alert.status.value},
    )
    await db.commit()
    name = await db.scalar(select(m.User.full_name).where(m.User.id == alert.student_id))
    return _view(alert, name or "", actor)
