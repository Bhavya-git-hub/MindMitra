"""Raising a support alert: the one way a request for help reaches a person.

Used by the Get help button, a teacher's safety referral and the AI companion. The alert goes
to the student's primary care-team therapist. A student with no care-team therapist is not
left without anyone: the alert stays unassigned and every verified therapist at the
institution (the counselling team) is notified and can see it; the first to acknowledge it
takes it. Notifications say only that someone may need support, never what was written.

An alert is a request for a person to reach out. It is never a judgement about the student and
nothing acts on the student automatically.
"""

import dataclasses
import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application import institution_settings
from app.application.access import has_active_care_link
from app.application.notifications import notify
from app.application.therapist_access import is_verified
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import (
    AlertCategory,
    AlertDetector,
    AlertSeverity,
    AlertSource,
    AlertStatus,
    NotificationPriority,
    NotificationType,
    UserStatus,
)
from app.infrastructure.db.ids import uuid7

# An imminent alert is due sooner than the institution's usual acknowledgement time.
IMMINENT_ACK = dt.timedelta(minutes=5)
_RANK = {
    AlertSeverity.LOW: 0,
    AlertSeverity.MODERATE: 1,
    AlertSeverity.HIGH: 2,
    AlertSeverity.IMMINENT: 3,
}


@dataclasses.dataclass
class Escalation:
    alert: m.RiskAlert
    assigned_to_care_team: bool
    notified: int  # how many people were told
    already_open: bool = False  # an open alert from the same place was raised again instead


async def primary_care_therapist(
    db: AsyncSession, *, institution_id: uuid.UUID, student_id: uuid.UUID, now: dt.datetime
) -> uuid.UUID | None:
    """The student's primary therapist, if the care link is live right now."""
    therapist_id = await db.scalar(
        select(m.CareTeamMember.therapist_id)
        .where(
            m.CareTeamMember.student_id == student_id,
            m.CareTeamMember.institution_id == institution_id,
            m.CareTeamMember.starts_at <= now,
            m.CareTeamMember.ends_at.is_(None),
        )
        .order_by(m.CareTeamMember.role, m.CareTeamMember.starts_at)
        .limit(1)
    )
    if therapist_id is None:
        return None
    if not await has_active_care_link(
        db, therapist_id=therapist_id, student_id=student_id, now=now
    ):
        return None
    return therapist_id


async def counselling_team(db: AsyncSession, institution_id: uuid.UUID) -> list[uuid.UUID]:
    """Every active, currently verified therapist at the institution."""
    rows = await db.scalars(
        select(m.Therapist)
        .join(m.User, m.User.id == m.Therapist.user_id)
        .where(
            m.Therapist.institution_id == institution_id,
            m.User.status == UserStatus.ACTIVE,
            m.User.deleted_at.is_(None),
        )
    )
    return [t.user_id for t in rows if is_verified(t)]


def ack_due(severity: AlertSeverity, ack_minutes: int, now: dt.datetime) -> dt.datetime:
    usual = dt.timedelta(minutes=ack_minutes)
    return now + (min(usual, IMMINENT_ACK) if severity is AlertSeverity.IMMINENT else usual)


async def _notify_people(
    db: AsyncSession, alert: m.RiskAlert, title: str, assigned: uuid.UUID | None
) -> int:
    recipients = [assigned] if assigned else await counselling_team(db, alert.institution_id)
    priority = (
        NotificationPriority.CRITICAL
        if _RANK[alert.severity] >= _RANK[AlertSeverity.HIGH]
        else NotificationPriority.HIGH
    )
    for user_id in recipients:
        await notify(
            db,
            institution_id=alert.institution_id,
            user_id=user_id,
            type=NotificationType.RISK_ALERT,
            priority=priority,
            title=title,
            payload={"alert_id": str(alert.id)},
        )
    return len(recipients)


async def raise_alert(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    student_id: uuid.UUID,
    source: AlertSource,
    detector: AlertDetector,
    category: AlertCategory,
    severity: AlertSeverity,
    title: str,
    now: dt.datetime,
    excerpt: str | None = None,
    source_type: str | None = None,
    source_id: uuid.UUID | None = None,
    model_version: str | None = None,
) -> Escalation:
    """Create the alert and tell the people who should act on it. The caller commits."""
    assigned = await primary_care_therapist(
        db, institution_id=institution_id, student_id=student_id, now=now
    )
    safety = (await institution_settings.load(db, institution_id)).safety
    alert = m.RiskAlert(
        id=uuid7(),
        institution_id=institution_id,
        student_id=student_id,
        assigned_to=assigned,
        source=source,
        source_type=source_type,
        source_id=source_id,
        detector=detector,
        category=category,
        severity=severity,
        status=AlertStatus.OPEN,
        requires_human=True,
        excerpt=excerpt,
        model_version=model_version,
        sla_ack_due_at=ack_due(severity, safety.alert_ack_minutes, now),
    )
    db.add(alert)
    await db.flush()
    notified = await _notify_people(db, alert, title, assigned)
    return Escalation(alert, assigned is not None, notified)


async def raise_severity(
    db: AsyncSession, alert: m.RiskAlert, severity: AlertSeverity, *, title: str, now: dt.datetime
) -> int:
    """A still-open alert became more urgent: raise it, bring its deadline forward and tell
    the same people again. Returns how many were told (0 if it was not more urgent)."""
    if _RANK[severity] <= _RANK[alert.severity]:
        return 0
    safety = (await institution_settings.load(db, alert.institution_id)).safety
    alert.severity = severity
    due = ack_due(severity, safety.alert_ack_minutes, now)
    if alert.sla_ack_due_at is None or due < alert.sla_ack_due_at:
        alert.sla_ack_due_at = due
    await db.flush()
    return await _notify_people(db, alert, title, alert.assigned_to)


async def raise_or_reuse(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    student_id: uuid.UUID,
    source: AlertSource,
    detector: AlertDetector,
    category: AlertCategory,
    severity: AlertSeverity,
    title: str,
    now: dt.datetime,
    reuse_window: dt.timedelta,
    source_type: str | None = None,
    source_id: uuid.UUID | None = None,
    model_version: str | None = None,
) -> Escalation:
    """Raise an alert, unless one from the same place is still open from within
    ``reuse_window``: then that one is raised in urgency (and its people told again) instead,
    so a student writing several worried messages does not flood the team. The caller
    commits."""
    existing = await db.scalar(
        select(m.RiskAlert)
        .where(
            m.RiskAlert.student_id == student_id,
            m.RiskAlert.institution_id == institution_id,
            m.RiskAlert.source == source,
            m.RiskAlert.status.in_(
                (AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED, AlertStatus.IN_PROGRESS)
            ),
            m.RiskAlert.created_at > now - reuse_window,
        )
        .order_by(m.RiskAlert.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if existing is not None:
        notified = await raise_severity(db, existing, severity, title=title, now=now)
        return Escalation(existing, existing.assigned_to is not None, notified, already_open=True)
    return await raise_alert(
        db,
        institution_id=institution_id,
        student_id=student_id,
        source=source,
        detector=detector,
        category=category,
        severity=severity,
        title=title,
        now=now,
        source_type=source_type,
        source_id=source_id,
        model_version=model_version,
    )
