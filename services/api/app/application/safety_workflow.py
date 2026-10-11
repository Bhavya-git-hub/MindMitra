"""EscalationWorkflow: one path from a safety assessment to what the student sees and who is
told (ADR 0013).

    words or numbers -> SafetyClassifier -> RiskLevel -> SafetyPolicy -> this workflow:
      guidance + EmergencyResources + counsellor access  (always, at MODERATE and above)
      pause normal suggestions + SafetyEvent             (HIGH and IMMEDIATE)
      HumanEscalation through ``escalation.raise_or_reuse`` (where the policy allows)

It is not a replacement for emergency services or qualified professionals. It can only show
people where help is and ask a person to reach out; it never diagnoses or treats anyone.

Fail safe: each step is guarded on its own. If asking a person fails, the student is told to
contact someone directly; if contacts cannot be loaded, the built-in emergency entry is shown.
Nothing here stores or logs what the student wrote.
"""

import dataclasses
import datetime as dt
import enum
import logging
import uuid
from typing import Final

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.access import has_active_consent
from app.application.escalation import primary_care_therapist, raise_or_reuse
from app.application.safety import crisis_contacts
from app.application.timeutil import now_utc
from app.domain.auth.policies import Principal
from app.domain.safety.classifier import SafetyAssessment
from app.domain.safety.guidance import DISCLAIMER, Guidance, guidance_for
from app.domain.safety.policy import DEFAULT_POLICY, EscalationBasis, SafetyDecision, SafetyPolicy
from app.domain.safety.resources import FALLBACK, EmergencyResource, arrange
from app.domain.safety.risk import Concern, Detector, RiskLevel, Source
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
    UserRole,
)
from app.infrastructure.db.ids import uuid7

log = logging.getLogger("mindmitra.safety")

ALERT_TITLE: Final = "A student may need support now"
EVENT_RETENTION: Final = dt.timedelta(days=90)
MESSAGE_PATH: Final = "/student/messages"
BOOKING_PATH: Final = "/student/therapists"

_ALERT_CATEGORY: Final = {
    Concern.SUICIDAL_LANGUAGE: AlertCategory.SUICIDAL_LANGUAGE,
    Concern.SELF_HARM_LANGUAGE: AlertCategory.SELF_HARM_LANGUAGE,
    Concern.HARM_TO_OTHERS: AlertCategory.HARM_TO_OTHERS,
    Concern.UNSAFE_SITUATION: AlertCategory.UNSAFE_SITUATION,
    Concern.ACUTE_DISTRESS: AlertCategory.ACUTE_DISTRESS,
}
_ALERT_SOURCE: Final = {
    Source.CHECK_IN: AlertSource.MOOD_ENTRY,
    Source.COMPANION: AlertSource.AI_CHAT,
    Source.MESSAGE: AlertSource.MESSAGE,
}
_ALERT_SEVERITY: Final = {
    "moderate": AlertSeverity.MODERATE,
    "high": AlertSeverity.HIGH,
    "imminent": AlertSeverity.IMMINENT,
}
# An alert someone has closed no longer holds suggestions back.
_CLOSED: Final = (AlertStatus.RESOLVED, AlertStatus.DISMISSED)


class EscalationStatus(enum.StrEnum):
    REQUESTED = "requested"  # a person has been asked to reach out
    ALREADY_OPEN = "already_open"  # a person was already asked, and has been told again
    NOT_REQUESTED = "not_requested"  # the policy did not ask anyone (see the basis)
    FAILED = "failed"  # asking failed: the student is told to contact someone directly


@dataclasses.dataclass
class HumanEscalation:
    status: EscalationStatus
    basis: EscalationBasis
    alert_id: uuid.UUID | None = None
    care_team_notified: bool = False  # their own therapist, rather than the counselling team

    @property
    def requested(self) -> bool:
        return self.status in (EscalationStatus.REQUESTED, EscalationStatus.ALREADY_OPEN)


@dataclasses.dataclass(frozen=True)
class CounsellingAccess:
    has_care_team: bool
    message_path: str | None  # their therapist's messages, when they have a care team
    booking_path: str = BOOKING_PATH


@dataclasses.dataclass
class SafetyOutcome:
    level: RiskLevel
    about_someone_else: bool
    decision: SafetyDecision
    guidance: Guidance
    resources: list[EmergencyResource]
    counselling: CounsellingAccess
    escalation: HumanEscalation
    hold_until: dt.datetime | None
    disclaimer: str = DISCLAIMER

    @property
    def recommendations_paused(self) -> bool:
        return self.hold_until is not None


class EscalationWorkflow:
    def __init__(self, policy: SafetyPolicy = DEFAULT_POLICY) -> None:
        self.policy = policy

    async def handle(
        self,
        db: AsyncSession,
        actor: Principal,
        assessment: SafetyAssessment,
        *,
        source: Source,
        now: dt.datetime | None = None,
        source_type: str | None = None,
        source_id: uuid.UUID | None = None,
        model_version: str | None = None,
    ) -> SafetyOutcome | None:
        """Act on one assessment. ``None`` at LOW. The caller commits (``commit`` below)."""
        if assessment.level is RiskLevel.LOW:
            return None
        now = now or now_utc()
        consent = False
        if self.policy.needs_consent(assessment, source):
            consent = await _scanning_consent(db, actor)
        decision = self.policy.decide(assessment, source=source, scanning_consent=consent)

        escalation = HumanEscalation(EscalationStatus.NOT_REQUESTED, decision.basis)
        if decision.escalate:
            escalation = await self._escalate(
                db, actor, assessment, decision, source, now, source_type, source_id, model_version
            )
        hold_until = None
        if decision.pause_recommendations:
            hold_until = now + dt.timedelta(hours=self.policy.hold_hours)
            if not await _record(db, actor, assessment, decision, escalation, source, hold_until):
                hold_until = None
        return SafetyOutcome(
            level=assessment.level,
            about_someone_else=assessment.about_someone_else,
            decision=decision,
            guidance=guidance_for(
                assessment.level,
                assessment.concern,
                about_someone_else=assessment.about_someone_else,
            ),
            resources=await emergency_resources(db, actor, assessment.level),
            counselling=await counselling_access(db, actor, now),
            escalation=escalation,
            hold_until=hold_until,
        )

    async def _escalate(
        self,
        db: AsyncSession,
        actor: Principal,
        assessment: SafetyAssessment,
        decision: SafetyDecision,
        source: Source,
        now: dt.datetime,
        source_type: str | None,
        source_id: uuid.UUID | None,
        model_version: str | None,
    ) -> HumanEscalation:
        try:
            async with db.begin_nested():
                done = await raise_or_reuse(
                    db,
                    institution_id=actor.institution_id,
                    student_id=actor.user_id,
                    source=_ALERT_SOURCE[source],
                    detector=AlertDetector((assessment.detector or Detector.RULES).value),
                    category=_ALERT_CATEGORY.get(
                        assessment.concern or Concern.ACUTE_DISTRESS, AlertCategory.ACUTE_DISTRESS
                    ),
                    severity=_ALERT_SEVERITY.get(
                        assessment.alert_severity or "", AlertSeverity.HIGH
                    ),
                    title=ALERT_TITLE,
                    now=now,
                    reuse_window=dt.timedelta(hours=self.policy.alert_reuse_hours),
                    source_type=source_type,
                    source_id=source_id,
                    model_version=model_version or assessment.rules_version,
                )
        except Exception:
            log.exception("could not ask a person to reach out; the student is told to call")
            return HumanEscalation(EscalationStatus.FAILED, decision.basis)
        return HumanEscalation(
            EscalationStatus.ALREADY_OPEN if done.already_open else EscalationStatus.REQUESTED,
            decision.basis,
            done.alert.id,
            done.assigned_to_care_team,
        )


WORKFLOW: Final = EscalationWorkflow()


async def commit(db: AsyncSession, outcome: SafetyOutcome | None) -> SafetyOutcome | None:
    """Commit what ``handle`` did. If that fails, nothing was saved: the student is told
    nobody could be asked, so they contact someone themselves."""
    try:
        await db.commit()
    except Exception:
        log.exception("could not save a safety outcome")
        await db.rollback()
        if outcome is not None:
            if outcome.escalation.requested:
                outcome.escalation = HumanEscalation(
                    EscalationStatus.FAILED, outcome.escalation.basis
                )
            outcome.hold_until = None
    return outcome


async def act(
    db: AsyncSession,
    actor: Principal,
    assessment: SafetyAssessment,
    *,
    source: Source,
    now: dt.datetime | None = None,
    source_type: str | None = None,
    source_id: uuid.UUID | None = None,
) -> SafetyOutcome | None:
    """``handle`` then ``commit``, for callers whose own record is already saved. Whatever
    fails, a student at MODERATE or above still gets guidance and the emergency entry."""
    try:
        outcome = await WORKFLOW.handle(
            db, actor, assessment, source=source, now=now, source_type=source_type,
            source_id=source_id,
        )  # fmt: skip
    except Exception:
        log.exception("the safety workflow failed; showing built-in support")
        await db.rollback()
        return fail_safe(assessment, source)
    return await commit(db, outcome)


def fail_safe(assessment: SafetyAssessment, source: Source) -> SafetyOutcome | None:
    """Support built without the database: guidance and the built-in emergency entry. At a
    level where a person might have been asked, nobody was, so it is reported as failed and
    the student is asked to contact someone themselves."""
    if assessment.level is RiskLevel.LOW:
        return None
    decision = DEFAULT_POLICY.decide(assessment, source=source)
    serious = assessment.level.at_least(DEFAULT_POLICY.escalate_at)
    status = EscalationStatus.FAILED if serious else EscalationStatus.NOT_REQUESTED
    return SafetyOutcome(
        level=assessment.level,
        about_someone_else=assessment.about_someone_else,
        decision=decision,
        guidance=guidance_for(
            assessment.level, assessment.concern, about_someone_else=assessment.about_someone_else
        ),
        resources=arrange([], assessment.level),
        counselling=CounsellingAccess(False, None),
        escalation=HumanEscalation(status, decision.basis),
        hold_until=None,
    )


# ---- the pieces -----------------------------------------------------------------------------


async def _scanning_consent(db: AsyncSession, actor: Principal) -> bool:
    try:
        return await has_active_consent(
            db, user_id=actor.user_id, scope=ConsentScope.JOURNAL_SAFETY_SCANNING
        )
    except Exception:  # unknown counts as "no": immediate danger still escalates
        log.exception("could not read the safety-check consent")
        return False


async def _record(
    db: AsyncSession,
    actor: Principal,
    assessment: SafetyAssessment,
    decision: SafetyDecision,
    escalation: HumanEscalation,
    source: Source,
    hold_until: dt.datetime,
) -> bool:
    """Store the minimum: no text, no rule ids, no link to what was written."""
    try:
        async with db.begin_nested():
            event = m.SafetyEvent(
                id=uuid7(),
                institution_id=actor.institution_id,
                student_id=actor.user_id,
                source=source,
                risk_level=assessment.level,
                concern=assessment.concern or Concern.ACUTE_DISTRESS,
                detector=assessment.detector or Detector.RULES,
                rules_version=assessment.rules_version,
                escalated=escalation.requested,
                basis=decision.basis,
                alert_id=escalation.alert_id,
                recommendations_paused=True,
                hold_until=hold_until,
            )
            db.add(event)
            await db.flush()
            await append_audit_event(
                db,
                institution_id=actor.institution_id,
                actor_id=actor.user_id,
                actor_role=UserRole.STUDENT,
                action="safety_event.create",
                outcome=AuditOutcome.ALLOWED,
                resource_type="safety_event",
                resource_id=event.id,
                subject_student_id=actor.user_id,
                details={
                    "level": assessment.level.value,
                    "source": source.value,
                    "basis": decision.basis.value,
                    "escalated": escalation.requested,
                },
            )
    except Exception:
        log.exception("could not record a safety event; suggestions are not paused")
        return False
    return True


def _resource(c: m.CrisisContact) -> EmergencyResource:
    return EmergencyResource(
        id=c.id,
        label=c.label,
        kind=c.kind.value,
        phone=c.phone,
        url=c.url,
        description=c.description,
        hours=c.hours,
    )


async def emergency_resources(
    db: AsyncSession, actor: Principal, level: RiskLevel
) -> list[EmergencyResource]:
    """The institution's and national contacts, in the order the level calls for; never
    empty."""
    try:
        rows = await crisis_contacts(db, actor)
    except Exception:
        log.exception("could not load crisis contacts; showing the built-in entry")
        return [FALLBACK]
    return arrange((_resource(c) for c in rows), level)


async def counselling_access(
    db: AsyncSession, actor: Principal, now: dt.datetime
) -> CounsellingAccess:
    try:
        therapist = await primary_care_therapist(
            db, institution_id=actor.institution_id, student_id=actor.user_id, now=now
        )
    except Exception:
        log.exception("could not look up the care team")
        therapist = None
    return CounsellingAccess(therapist is not None, MESSAGE_PATH if therapist else None)


# ---- the pause on normal suggestions --------------------------------------------------------


async def active_hold(
    db: AsyncSession, actor: Principal, now: dt.datetime | None = None
) -> m.SafetyEvent | None:
    """The latest event still pausing suggestions: within its hold, and its alert (if any)
    not yet resolved or dismissed by a person."""
    now = now or now_utc()
    return await db.scalar(
        select(m.SafetyEvent)
        .outerjoin(m.RiskAlert, m.RiskAlert.id == m.SafetyEvent.alert_id)
        .where(
            m.SafetyEvent.student_id == actor.user_id,
            m.SafetyEvent.institution_id == actor.institution_id,
            m.SafetyEvent.recommendations_paused.is_(True),
            m.SafetyEvent.hold_until > now,
            (m.RiskAlert.id.is_(None)) | (m.RiskAlert.status.not_in(_CLOSED)),
        )
        .order_by(m.SafetyEvent.created_at.desc())
        .limit(1)
    )


async def hold_outcome(
    db: AsyncSession, actor: Principal, event: m.SafetyEvent, now: dt.datetime | None = None
) -> SafetyOutcome:
    """What to show while suggestions are paused, rebuilt from the stored event."""
    now = now or now_utc()
    level = event.risk_level
    decision = DEFAULT_POLICY.decide(
        SafetyAssessment(level, event.concern), source=event.source, scanning_consent=False
    )
    decision = dataclasses.replace(
        decision, basis=event.basis, escalate=event.escalated, offer_outreach=not event.escalated
    )
    status = EscalationStatus.REQUESTED if event.escalated else EscalationStatus.NOT_REQUESTED
    alert = await db.get(m.RiskAlert, event.alert_id) if event.alert_id else None
    return SafetyOutcome(
        level=level,
        about_someone_else=False,
        decision=decision,
        guidance=guidance_for(level, event.concern),
        resources=await emergency_resources(db, actor, level),
        counselling=await counselling_access(db, actor, now),
        escalation=HumanEscalation(
            status,
            event.basis,
            event.alert_id,
            alert is not None and alert.assigned_to is not None,
        ),
        hold_until=event.hold_until,
    )


async def sweep_safety_events(db: AsyncSession, now: dt.datetime | None = None) -> int:
    """Deletes events older than the retention period. Alerts are kept by their own policy."""
    result = await db.execute(
        delete(m.SafetyEvent).where(m.SafetyEvent.created_at < (now or now_utc()) - EVENT_RETENTION)
    )
    await db.commit()
    return int(getattr(result, "rowcount", 0) or 0)
