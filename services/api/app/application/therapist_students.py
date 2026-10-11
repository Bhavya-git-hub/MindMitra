"""A therapist's caseload: who is on their care team, and what each student has chosen to share.

Two separate gates apply, and both are checked here and again in the route guard:

* the care team (the student is "mine") lets a therapist see that a student exists, their
  course context, appointments with this therapist, sessions, alerts and follow-ups;
* the student's consent (``share_mood_with_care_team`` / ``share_assessments_with_care_team``
  / ``share_ai_signals_with_care_team``) is additionally needed to read their check-in trends,
  wellbeing questionnaires or AI wellness indicators.

Without consent the profile says so (``sharing``) instead of silently showing nothing, and the
consent-gated endpoints answer 403. Every profile, trend and assessment read is audited with
counts only.
"""

import dataclasses
import datetime as dt
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application import student_wellness, wellness_indicators
from app.application.access import enforce, has_active_consent
from app.application.errors import InvalidInput
from app.application.risk_alerts import OPEN_STATUSES
from app.application.therapist_access import require_verified, student_in_care
from app.application.timeutil import now_utc
from app.domain.auth.policies import Principal, can_read_student_wellness
from app.infrastructure.db import models as m
from app.infrastructure.db.audit import append_audit_event
from app.infrastructure.db.enums import (
    AppointmentStatus,
    AuditOutcome,
    CareRole,
    ConsentScope,
    FollowUpStatus,
    UserRole,
)
from app.infrastructure.ml_client import IndicatorClient

LIVE = (AppointmentStatus.REQUESTED, AppointmentStatus.CONFIRMED)
MAX_CASELOAD_ROWS = 200


@dataclasses.dataclass
class Sharing:
    mood: bool
    assessments: bool


@dataclasses.dataclass
class CaseloadRow:
    student: m.Student
    name: str
    care_role: CareRole
    since: dt.datetime
    next_appointment: m.Appointment | None
    last_session_at: dt.datetime | None
    open_alerts: int
    open_follow_ups: int
    sharing: Sharing


@dataclasses.dataclass
class SessionRow:
    session: m.TherapySession
    has_note: bool


@dataclasses.dataclass
class LatestMood:
    score: int
    logged_at: dt.datetime


@dataclasses.dataclass
class LatestAssessment:
    score: float
    max_score: float
    completed_at: dt.datetime


@dataclasses.dataclass
class StudentProfile:
    student: m.Student
    name: str
    department: str
    care_role: CareRole
    since: dt.datetime
    sharing: Sharing
    upcoming: list[m.Appointment]
    sessions: list[SessionRow]
    open_alerts: int
    open_follow_ups: int
    latest_mood: LatestMood | None
    latest_assessment: LatestAssessment | None


async def _audit(
    db: AsyncSession,
    actor: Principal,
    action: str,
    resource_type: str,
    student_id: uuid.UUID | None,
    **d: object,
) -> None:
    await append_audit_event(
        db,
        institution_id=actor.institution_id,
        actor_id=actor.user_id,
        actor_role=UserRole.THERAPIST,
        action=action,
        outcome=AuditOutcome.ALLOWED,
        resource_type=resource_type,
        subject_student_id=student_id,
        details=dict(d),
    )


async def _consents(db: AsyncSession, student_ids: list[uuid.UUID]) -> dict[uuid.UUID, Sharing]:
    """Which active consents each student currently has (one query for the whole list)."""
    out = {sid: Sharing(False, False) for sid in student_ids}
    if not student_ids:
        return out
    rows = await db.execute(
        select(m.Consent.user_id, m.Consent.scope).where(
            m.Consent.user_id.in_(student_ids),
            m.Consent.revoked_at.is_(None),
            m.Consent.scope.in_(
                (
                    ConsentScope.SHARE_MOOD_WITH_CARE_TEAM,
                    ConsentScope.SHARE_ASSESSMENTS_WITH_CARE_TEAM,
                )
            ),
        )
    )
    for uid, scope in rows.all():
        if scope is ConsentScope.SHARE_MOOD_WITH_CARE_TEAM:
            out[uid].mood = True
        else:
            out[uid].assessments = True
    return out


async def caseload(db: AsyncSession, actor: Principal) -> list[CaseloadRow]:
    await require_verified(db, actor, "student.list")
    now = now_utc()
    rows = (
        await db.execute(
            select(m.Student, m.User.full_name, m.CareTeamMember)
            .join(m.User, m.User.id == m.Student.user_id)
            .join(m.CareTeamMember, m.CareTeamMember.student_id == m.Student.user_id)
            .where(
                m.CareTeamMember.therapist_id == actor.user_id,
                m.CareTeamMember.institution_id == actor.institution_id,
                m.CareTeamMember.starts_at <= now,
                (m.CareTeamMember.ends_at.is_(None)) | (m.CareTeamMember.ends_at > now),
            )
            .order_by(m.User.full_name)
            .limit(MAX_CASELOAD_ROWS)
        )
    ).all()
    ids = [s.user_id for s, _, _ in rows]
    sharing = await _consents(db, ids)

    next_by: dict[uuid.UUID, m.Appointment] = {}
    last_session: dict[uuid.UUID, dt.datetime] = {}
    alerts: dict[uuid.UUID, int] = {}
    follow_ups: dict[uuid.UUID, int] = {}
    if ids:
        upcoming = await db.scalars(
            select(m.Appointment)
            .where(
                m.Appointment.therapist_id == actor.user_id,
                m.Appointment.student_id.in_(ids),
                m.Appointment.status.in_(LIVE),
                m.Appointment.ends_at >= now,
            )
            .order_by(m.Appointment.starts_at.desc())  # last write wins -> the earliest
        )
        for appt in upcoming:
            next_by[appt.student_id] = appt
        for sid, at in await db.execute(
            select(m.TherapySession.student_id, func.max(m.TherapySession.started_at))
            .where(
                m.TherapySession.therapist_id == actor.user_id,
                m.TherapySession.student_id.in_(ids),
            )
            .group_by(m.TherapySession.student_id)
        ):
            last_session[sid] = at
        for sid, n in await db.execute(
            select(m.RiskAlert.student_id, func.count())
            .where(
                m.RiskAlert.institution_id == actor.institution_id,
                m.RiskAlert.student_id.in_(ids),
                m.RiskAlert.status.in_(OPEN_STATUSES),
                (m.RiskAlert.assigned_to == actor.user_id) | m.RiskAlert.assigned_to.is_(None),
            )
            .group_by(m.RiskAlert.student_id)
        ):
            alerts[sid] = n
        for sid, n in await db.execute(
            select(m.FollowUp.student_id, func.count())
            .where(
                m.FollowUp.therapist_id == actor.user_id,
                m.FollowUp.student_id.in_(ids),
                m.FollowUp.status == FollowUpStatus.OPEN,
            )
            .group_by(m.FollowUp.student_id)
        ):
            follow_ups[sid] = n
    await _audit(db, actor, "student.list", "student", None, count=len(rows))
    await db.commit()
    return [
        CaseloadRow(
            student=s,
            name=name,
            care_role=c.role,
            since=c.starts_at,
            next_appointment=next_by.get(s.user_id),
            last_session_at=last_session.get(s.user_id),
            open_alerts=alerts.get(s.user_id, 0),
            open_follow_ups=follow_ups.get(s.user_id, 0),
            sharing=sharing[s.user_id],
        )
        for s, name, c in rows
    ]


async def profile(db: AsyncSession, actor: Principal, student_id: uuid.UUID) -> StudentProfile:
    student = await student_in_care(
        db, actor, student_id, action="student.read", resource_type="student"
    )
    now = now_utc()
    link = await db.scalar(
        select(m.CareTeamMember)
        .where(
            m.CareTeamMember.therapist_id == actor.user_id,
            m.CareTeamMember.student_id == student_id,
            m.CareTeamMember.starts_at <= now,
            (m.CareTeamMember.ends_at.is_(None)) | (m.CareTeamMember.ends_at > now),
        )
        .order_by(m.CareTeamMember.starts_at.desc())
        .limit(1)
    )
    assert link is not None  # student_in_care just proved the link exists
    name = await db.scalar(select(m.User.full_name).where(m.User.id == student_id)) or ""
    department = (
        await db.scalar(select(m.Department.name).where(m.Department.id == student.department_id))
        or ""
    )
    sharing = (await _consents(db, [student_id]))[student_id]

    upcoming = list(
        await db.scalars(
            select(m.Appointment)
            .where(
                m.Appointment.therapist_id == actor.user_id,
                m.Appointment.student_id == student_id,
                m.Appointment.status.in_(LIVE),
                m.Appointment.ends_at >= now,
            )
            .order_by(m.Appointment.starts_at)
            .limit(5)
        )
    )
    sessions = list(
        await db.scalars(
            select(m.TherapySession)
            .where(
                m.TherapySession.therapist_id == actor.user_id,
                m.TherapySession.student_id == student_id,
            )
            .order_by(m.TherapySession.started_at.desc())
            .limit(10)
        )
    )
    with_notes: set[uuid.UUID] = set()
    if sessions:
        with_notes = set(
            await db.scalars(
                select(m.TherapyNote.session_id)
                .where(
                    m.TherapyNote.session_id.in_([s.id for s in sessions]),
                    m.TherapyNote.author_id == actor.user_id,
                )
                .distinct()
            )
        )
    open_alerts = int(
        await db.scalar(
            select(func.count())
            .select_from(m.RiskAlert)
            .where(
                m.RiskAlert.student_id == student_id,
                m.RiskAlert.institution_id == actor.institution_id,
                m.RiskAlert.status.in_(OPEN_STATUSES),
                (m.RiskAlert.assigned_to == actor.user_id) | m.RiskAlert.assigned_to.is_(None),
            )
        )
        or 0
    )
    open_follow_ups = int(
        await db.scalar(
            select(func.count())
            .select_from(m.FollowUp)
            .where(
                m.FollowUp.therapist_id == actor.user_id,
                m.FollowUp.student_id == student_id,
                m.FollowUp.status == FollowUpStatus.OPEN,
            )
        )
        or 0
    )

    latest_mood: LatestMood | None = None
    if sharing.mood:  # the consent was just read; the policy is enforced again in trends()
        row = (
            await db.execute(
                select(m.MoodEntry.mood_score, m.MoodEntry.logged_at)
                .where(m.MoodEntry.student_id == student_id)
                .order_by(m.MoodEntry.logged_at.desc())
                .limit(1)
            )
        ).first()
        if row is not None:
            latest_mood = LatestMood(row[0], row[1])
    latest_assessment: LatestAssessment | None = None
    if sharing.assessments:
        arow = (
            await db.execute(
                select(
                    m.WellnessAssessment.score,
                    m.WellnessAssessment.max_score,
                    m.WellnessAssessment.completed_at,
                )
                .where(m.WellnessAssessment.student_id == student_id)
                .order_by(m.WellnessAssessment.completed_at.desc())
                .limit(1)
            )
        ).first()
        if arow is not None:
            latest_assessment = LatestAssessment(float(arow[0]), float(arow[1]), arow[2])

    await _audit(
        db,
        actor,
        "student.read",
        "student",
        student_id,
        mood_shared=sharing.mood,
        assessments_shared=sharing.assessments,
    )
    await db.commit()
    return StudentProfile(
        student=student,
        name=name,
        department=department,
        care_role=link.role,
        since=link.starts_at,
        sharing=sharing,
        upcoming=upcoming,
        sessions=[SessionRow(s, s.id in with_notes) for s in sessions],
        open_alerts=open_alerts,
        open_follow_ups=open_follow_ups,
        latest_mood=latest_mood,
        latest_assessment=latest_assessment,
    )


async def _consented_student(
    db: AsyncSession,
    actor: Principal,
    student_id: uuid.UUID,
    scope: ConsentScope,
    *,
    action: str,
    resource_type: str,
) -> m.Student:
    """The student, if the caller is verified, has them on the care team *and* they consented
    to this kind of sharing. Missing care link -> 404, missing consent -> 403."""
    student = await student_in_care(
        db, actor, student_id, action=action, resource_type=resource_type
    )
    consented = await has_active_consent(db, user_id=student_id, scope=scope)
    enforce(
        can_read_student_wellness(
            actor,
            student_id=student_id,
            student_institution_id=student.institution_id,
            has_active_care_link=True,
            has_sharing_consent=consented,
        ),
        action=action,
        resource_type=resource_type,
        subject_student_id=student_id,
    )
    return student


async def trends(
    db: AsyncSession, actor: Principal, student_id: uuid.UUID, days: int, zone: ZoneInfo
) -> list[student_wellness.DailyPoint]:
    student = await _consented_student(
        db,
        actor,
        student_id,
        ConsentScope.SHARE_MOOD_WITH_CARE_TEAM,
        action="wellness_trend.read",
        resource_type="wellness_trend",
    )
    series = await student_wellness.series_for_student(
        db, student_id, student.institution_id, days, zone
    )
    await _audit(db, actor, "wellness_trend.read", "wellness_trend", student_id, days=days)
    await db.commit()
    return series


async def indicators(
    db: AsyncSession,
    actor: Principal,
    student_id: uuid.UUID,
    zone: ZoneInfo,
    client: IndicatorClient | None,
) -> wellness_indicators.Result:
    """The AI wellness indicators, for a student who shares them with their care team. The
    student's private notes are not read or sent, so the note-tone indicator is left out."""
    student = await _consented_student(
        db,
        actor,
        student_id,
        ConsentScope.SHARE_AI_SIGNALS_WITH_CARE_TEAM,
        action="wellness_indicator.read",
        resource_type="wellness_indicator",
    )
    if client is None:
        raise wellness_indicators.IndicatorsOff("not configured")
    window_end, days, _ = await wellness_indicators.collect(
        db, student_id, student.institution_id, zone, with_notes=False
    )
    report = await wellness_indicators.score(client, window_end, days, [])
    out = wellness_indicators.result(window_end, report, include_note_tone=False)
    await _audit(
        db,
        actor,
        "wellness_indicator.read",
        "wellness_indicator",
        student_id,
        checkin_days=out.checkin_days,
        indicators=len(out.indicators),
    )
    await db.commit()
    return out


async def assessments(
    db: AsyncSession, actor: Principal, student_id: uuid.UUID, limit: int
) -> list[m.WellnessAssessment]:
    if not 1 <= limit <= 100:
        raise InvalidInput("limit must be between 1 and 100.")
    await _consented_student(
        db,
        actor,
        student_id,
        ConsentScope.SHARE_ASSESSMENTS_WITH_CARE_TEAM,
        action="wellness_assessment.list",
        resource_type="wellness_assessment",
    )
    rows = list(
        await db.scalars(
            select(m.WellnessAssessment)
            .where(
                m.WellnessAssessment.student_id == student_id,
                m.WellnessAssessment.institution_id == actor.institution_id,
            )
            .order_by(m.WellnessAssessment.completed_at.desc())
            .limit(limit)
        )
    )
    await _audit(
        db, actor, "wellness_assessment.list", "wellness_assessment", student_id, count=len(rows)
    )
    await db.commit()
    return rows
