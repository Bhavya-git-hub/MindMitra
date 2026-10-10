"""A student's privacy controls: consents, who has looked at their data, a copy of their data,
and the "I'd like someone to reach out" request."""

import dataclasses
import datetime as dt
import enum
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application import cohort_stats, institution_settings
from app.application.access import has_active_care_link
from app.application.auth.errors import Conflict
from app.application.errors import InvalidInput
from app.application.notifications import notify
from app.application.student_wellness import authorize_own
from app.application.timeutil import now_utc
from app.core.config import Settings
from app.domain.auth.policies import Principal
from app.domain.consent_scopes import BY_SCOPE, SCOPES, ScopeInfo
from app.infrastructure.db import models as m
from app.infrastructure.db.audit import append_audit_event
from app.infrastructure.db.enums import (
    AlertCategory,
    AlertDetector,
    AlertSeverity,
    AlertSource,
    AlertStatus,
    AuditOutcome,
    ConsentScope,
    NotificationPriority,
    NotificationType,
    UserRole,
)
from app.infrastructure.db.ids import uuid7

HELP_REQUEST_COOLDOWN = dt.timedelta(minutes=10)
MAX_HELP_MESSAGE = 1000


# ---- consent --------------------------------------------------------------------------------


@dataclasses.dataclass
class ConsentState:
    info: ScopeInfo
    granted: bool
    granted_at: dt.datetime | None
    policy_version: str | None


async def list_consents(db: AsyncSession, actor: Principal) -> list[ConsentState]:
    authorize_own(db, actor, "consent.list", "consent")
    active = {
        c.scope: c
        for c in await db.scalars(
            select(m.Consent).where(
                m.Consent.user_id == actor.user_id,
                m.Consent.institution_id == actor.institution_id,
                m.Consent.revoked_at.is_(None),
            )
        )
    }
    return [
        ConsentState(
            info=info,
            granted=info.scope in active,
            granted_at=active[info.scope].granted_at if info.scope in active else None,
            policy_version=active[info.scope].policy_version if info.scope in active else None,
        )
        for info in SCOPES
    ]


async def set_consent(
    db: AsyncSession, actor: Principal, scope: ConsentScope, granted: bool, settings: Settings
) -> ConsentState:
    authorize_own(db, actor, "consent.update", "consent")
    info = BY_SCOPE[scope]
    if info.required and not granted:
        raise Conflict("This consent can't be withdrawn here. Please contact the privacy team.")
    now = now_utc()
    current = await db.scalar(
        select(m.Consent).where(
            m.Consent.user_id == actor.user_id,
            m.Consent.institution_id == actor.institution_id,
            m.Consent.scope == scope,
            m.Consent.revoked_at.is_(None),
        )
    )
    changed = False
    if granted and current is None:
        current = m.Consent(
            id=uuid7(),
            institution_id=actor.institution_id,
            user_id=actor.user_id,
            scope=scope,
            policy_version=settings.terms_policy_version,
            source="web",
            granted_at=now,
        )
        db.add(current)
        try:
            async with db.begin_nested():
                await db.flush()
        except IntegrityError:  # a concurrent grant won; that is the same outcome
            current = await db.scalar(
                select(m.Consent).where(
                    m.Consent.user_id == actor.user_id,
                    m.Consent.scope == scope,
                    m.Consent.revoked_at.is_(None),
                )
            )
        changed = True
    elif not granted and current is not None:
        current.revoked_at = max(now, current.granted_at)
        changed = True
    if changed:
        # Stored group figures may include this student; they are rebuilt from live consent.
        await cohort_stats.invalidate_for_student(db, actor.institution_id, actor.user_id)
        await append_audit_event(
            db,
            institution_id=actor.institution_id,
            actor_id=actor.user_id,
            actor_role=UserRole.STUDENT,
            action="consent.grant" if granted else "consent.revoke",
            outcome=AuditOutcome.ALLOWED,
            resource_type="consent",
            subject_student_id=actor.user_id,
            details={"scope": scope.value},
        )
    await db.commit()
    live = current if granted else None
    return ConsentState(
        info=info,
        granted=live is not None,
        granted_at=live.granted_at if live else None,
        policy_version=live.policy_version if live else None,
    )


# ---- who has accessed my data ---------------------------------------------------------------


@dataclasses.dataclass
class AccessEvent:
    occurred_at: dt.datetime
    actor_role: str | None
    action: str
    resource_type: str | None


async def access_history(db: AsyncSession, actor: Principal, limit: int) -> list[AccessEvent]:
    """Other people's successful reads of this student's data. Role-level only: no names, ids
    or content. Denied attempts are not listed (they are for the security team)."""
    authorize_own(db, actor, "access_history.read", "audit_log")
    rows = await db.execute(
        select(
            m.AuditLog.occurred_at,
            m.AuditLog.actor_role,
            m.AuditLog.action,
            m.AuditLog.resource_type,
        )
        .where(
            m.AuditLog.institution_id == actor.institution_id,
            m.AuditLog.subject_student_id == actor.user_id,
            m.AuditLog.outcome == AuditOutcome.ALLOWED,
            or_(m.AuditLog.actor_id.is_(None), m.AuditLog.actor_id != actor.user_id),
        )
        .order_by(m.AuditLog.seq.desc())
        .limit(min(limit, 200))
    )
    return [
        AccessEvent(at, role.value if role else None, action, rtype)
        for at, role, action, rtype in rows.all()
    ]


# ---- data export ----------------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return value


def _row(obj: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {f: _jsonable(getattr(obj, f)) for f in fields}


async def _all(db: AsyncSession, model: Any, actor: Principal, order: Any) -> list[Any]:
    return list(
        await db.scalars(
            select(model)
            .where(
                model.student_id == actor.user_id,
                model.institution_id == actor.institution_id,
            )
            .order_by(order)
        )
    )


async def export_data(db: AsyncSession, actor: Principal) -> dict[str, Any]:
    """Everything this student has recorded, as plain JSON. Excludes other people's words
    (therapist notes are the therapist's record, not the student's)."""
    authorize_own(db, actor, "data_export.create", "student_data")
    user = await db.get(m.User, actor.user_id)
    student = await db.get(m.Student, actor.user_id)
    assert user is not None and student is not None
    now = now_utc()

    messages = list(
        await db.scalars(
            select(m.Message)
            .where(
                m.Message.student_id == actor.user_id,
                m.Message.institution_id == actor.institution_id,
            )
            .order_by(m.Message.created_at)
        )
    )
    journals = list(
        await db.scalars(
            select(m.JournalEntry)
            .where(
                m.JournalEntry.student_id == actor.user_id,
                m.JournalEntry.institution_id == actor.institution_id,
                m.JournalEntry.deleted_at.is_(None),
            )
            .order_by(m.JournalEntry.created_at)
        )
    )
    appointments = await _all(db, m.Appointment, actor, m.Appointment.starts_at)
    consents = list(
        await db.scalars(
            select(m.Consent)
            .where(m.Consent.user_id == actor.user_id)
            .order_by(m.Consent.granted_at)
        )
    )
    data: dict[str, Any] = {
        "exported_at": now.isoformat(),
        "about": (
            "A copy of the information you have recorded in MindMitra. Notes written about you "
            "by a therapist belong to the therapist's clinical record and are not included."
        ),
        "profile": {
            "email": user.email,
            "full_name": user.full_name,
            "preferred_name": student.preferred_name,
            "pronouns": student.pronouns,
            "year_of_study": student.year_of_study,
        },
        "mood_entries": [
            _row(r, ("logged_at", "mood_score", "energy_level", "emotions", "note"))
            for r in await _all(db, m.MoodEntry, actor, m.MoodEntry.logged_at)
        ],
        "stress_entries": [
            _row(
                r,
                (
                    "completed_at",
                    "scale",
                    "score",
                    "max_score",
                    "perceived_stress_level",
                    "stressors",
                ),
            )
            for r in await _all(db, m.StressAssessment, actor, m.StressAssessment.completed_at)
        ],
        "sleep_entries": [
            _row(r, ("sleep_date", "bedtime", "wake_time", "duration_minutes", "quality"))
            for r in await _all(db, m.SleepEntry, actor, m.SleepEntry.sleep_date)
        ],
        "wellness_assessments": [
            _row(r, ("completed_at", "instrument", "score", "max_score", "responses"))
            for r in await _all(db, m.WellnessAssessment, actor, m.WellnessAssessment.completed_at)
        ],
        "goals": [
            _row(
                r,
                (
                    "title",
                    "description",
                    "category",
                    "status",
                    "target_value",
                    "current_value",
                    "unit",
                    "start_date",
                    "target_date",
                    "completed_at",
                ),
            )  # fmt: skip
            for r in await _all(db, m.WellnessGoal, actor, m.WellnessGoal.created_at)
        ],
        "recommendations": [
            _row(r, ("created_at", "title", "rationale", "status", "source"))
            for r in await _all(db, m.Recommendation, actor, m.Recommendation.created_at)
        ],
        "journal_entries": [_row(r, ("created_at", "title", "body", "mood_tag")) for r in journals],
        "appointments": [
            _row(r, ("starts_at", "ends_at", "mode", "status", "reason", "cancelled_at"))
            for r in appointments
        ],
        "messages": [
            {
                "sent_at": r.created_at.isoformat(),
                "from": "me" if r.sender_id == actor.user_id else "my therapist",
                "body": r.body,
            }
            for r in messages
        ],
        "consents": [
            _row(r, ("scope", "policy_version", "granted_at", "revoked_at")) for r in consents
        ],
    }
    await append_audit_event(
        db,
        institution_id=actor.institution_id,
        actor_id=actor.user_id,
        actor_role=UserRole.STUDENT,
        action="data_export.create",
        outcome=AuditOutcome.ALLOWED,
        resource_type="student_data",
        subject_student_id=actor.user_id,
    )
    await db.commit()
    return data


# ---- "I'd like someone to reach out" --------------------------------------------------------


@dataclasses.dataclass
class HelpRequestResult:
    alert: m.RiskAlert
    already_open: bool
    assigned_to_care_team: bool


async def request_support(
    db: AsyncSession, actor: Principal, message: str | None
) -> HelpRequestResult:
    """Creates a high-priority alert for a human to pick up. It is a request for a person to
    reach out, never an automated judgement about the student."""
    authorize_own(db, actor, "support_request.create", "risk_alert")
    text = (message or "").strip() or None
    if text and len(text) > MAX_HELP_MESSAGE:
        raise InvalidInput(f"Please keep your message under {MAX_HELP_MESSAGE} characters.")
    now = now_utc()
    recent = await db.scalar(
        select(m.RiskAlert)
        .where(
            m.RiskAlert.student_id == actor.user_id,
            m.RiskAlert.institution_id == actor.institution_id,
            m.RiskAlert.source == AlertSource.HELP_BUTTON,
            m.RiskAlert.status.in_((AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED)),
            m.RiskAlert.created_at > now - HELP_REQUEST_COOLDOWN,
        )
        .order_by(m.RiskAlert.created_at.desc())
        .limit(1)
    )
    if recent is not None:  # repeated taps must not flood the team: one request is already out
        return HelpRequestResult(recent, True, recent.assigned_to is not None)

    primary = await db.scalar(
        select(m.CareTeamMember.therapist_id)
        .where(
            m.CareTeamMember.student_id == actor.user_id,
            m.CareTeamMember.institution_id == actor.institution_id,
            m.CareTeamMember.starts_at <= now,
            m.CareTeamMember.ends_at.is_(None),
        )
        .order_by(m.CareTeamMember.role, m.CareTeamMember.starts_at)
        .limit(1)
    )
    assigned = primary
    if assigned is not None and not await has_active_care_link(
        db, therapist_id=assigned, student_id=actor.user_id, now=now
    ):
        assigned = None
    safety = (await institution_settings.load(db, actor.institution_id)).safety
    alert = m.RiskAlert(
        id=uuid7(),
        institution_id=actor.institution_id,
        student_id=actor.user_id,
        assigned_to=assigned,
        source=AlertSource.HELP_BUTTON,
        detector=AlertDetector.HUMAN,
        category=AlertCategory.ACUTE_DISTRESS,
        severity=AlertSeverity.HIGH,
        status=AlertStatus.OPEN,
        requires_human=True,
        excerpt=text,
        sla_ack_due_at=now + dt.timedelta(minutes=safety.alert_ack_minutes),
    )
    db.add(alert)
    await db.flush()
    if assigned is not None:
        await notify(
            db,
            institution_id=actor.institution_id,
            user_id=assigned,
            type=NotificationType.RISK_ALERT,
            priority=NotificationPriority.CRITICAL,
            title="A student has asked for support",
            payload={"alert_id": str(alert.id)},
        )
    await append_audit_event(
        db,
        institution_id=actor.institution_id,
        actor_id=actor.user_id,
        actor_role=UserRole.STUDENT,
        action="support_request.create",
        outcome=AuditOutcome.ALLOWED,
        resource_type="risk_alert",
        resource_id=alert.id,
        subject_student_id=actor.user_id,
    )
    await db.commit()
    return HelpRequestResult(alert, False, assigned is not None)
