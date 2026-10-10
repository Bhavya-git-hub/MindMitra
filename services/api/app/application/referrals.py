"""Referrals: a teacher asks the wellbeing team to reach out to a student in their class.

A referral is a request for a person to get in touch. It is never a judgement about the student
and it never exposes anything about them to the teacher:

* A teacher can raise one only for a student enrolled in a class they teach (checked here, and
  by foreign keys in the database).
* The teacher sees their own referrals' category, urgency, their own note and a status
  (received, with the wellbeing team, closed). They do not see who picked it up, what was said,
  or how it ended.
* Verified therapists triage the queue: their own students' referrals, plus those about students
  nobody is looking after yet. The student gets a short, neutral notification when someone
  picks it up; it carries no information about who raised it.
* A referral about safety also raises a high-priority alert so it cannot wait in a queue.
"""

import dataclasses
import datetime as dt
import uuid

from sqlalchemy import ColumnElement, case, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.access import NotFound, enforce
from app.application.auth.errors import Conflict
from app.application.care import InvalidTransition
from app.application.errors import InvalidInput
from app.application.escalation import raise_alert
from app.application.notifications import notify
from app.application.teacher_portal import audit as teacher_audit
from app.application.therapist_access import require_verified
from app.application.timeutil import now_utc
from app.domain.auth.policies import (
    Principal,
    can_manage_own_teacher_record,
    can_raise_referral,
    can_triage_referral,
    deny,
)
from app.infrastructure.db import models as m
from app.infrastructure.db.audit import append_audit_event
from app.infrastructure.db.enums import (
    AlertCategory,
    AlertDetector,
    AlertSeverity,
    AlertSource,
    AuditOutcome,
    EnrollmentStatus,
    NotificationPriority,
    NotificationType,
    ReferralCategory,
    ReferralOutcome,
    ReferralStatus,
    ReferralUrgency,
    UserRole,
    UserStatus,
)
from app.infrastructure.db.ids import uuid7

MAX_NOTE = 1000
DAILY_LIMIT = 10
URGENCY_RANK = {ReferralUrgency.URGENT: 0, ReferralUrgency.SOON: 1, ReferralUrgency.ROUTINE: 2}
TEACHER_STATUS_LABELS = {
    ReferralStatus.RECEIVED: "Received by the wellbeing team",
    ReferralStatus.IN_PROGRESS: "With the wellbeing team",
    ReferralStatus.CLOSED: "Closed",
}


@dataclasses.dataclass
class ReferralView:
    referral: m.Referral
    student_name: str
    course_code: str
    course_title: str


@dataclasses.dataclass
class TriageView(ReferralView):
    teacher_name: str
    department_name: str
    on_my_team: bool


def _display(preferred: str | None, full: str) -> str:
    return preferred or full


# ---- teacher side ---------------------------------------------------------------------------


async def create(
    db: AsyncSession,
    actor: Principal,
    *,
    student_id: uuid.UUID,
    course_id: uuid.UUID,
    category: ReferralCategory,
    urgency: ReferralUrgency,
    note: str | None,
) -> ReferralView:
    text = (note or "").strip() or None
    if text and len(text) > MAX_NOTE:
        raise InvalidInput(f"Please keep the note under {MAX_NOTE} characters.")

    course = await db.get(m.Course, course_id)
    student = await db.get(m.Student, student_id)
    if course is None or student is None:
        raise NotFound
    teaches = (
        await db.scalar(
            select(func.count())
            .select_from(m.CourseTeacher)
            .where(
                m.CourseTeacher.course_id == course_id,
                m.CourseTeacher.teacher_id == actor.user_id,
            )
        )
    ) == 1
    enrolled = (
        await db.scalar(
            select(func.count())
            .select_from(m.CourseEnrollment)
            .where(
                m.CourseEnrollment.course_id == course_id,
                m.CourseEnrollment.student_id == student_id,
                m.CourseEnrollment.status == EnrollmentStatus.ENROLLED,
            )
        )
    ) == 1
    enforce(
        can_raise_referral(
            actor,
            student_institution_id=student.institution_id,
            teaches_course=teaches,
            student_enrolled=enrolled,
        ),
        action="referral.create",
        resource_type="referral",
        subject_student_id=student_id,
    )
    user = await db.get(m.User, student_id)
    if user is None or user.status is not UserStatus.ACTIVE or user.deleted_at is not None:
        raise NotFound

    now = now_utc()
    today = await db.scalar(
        select(func.count())
        .select_from(m.Referral)
        .where(
            m.Referral.teacher_id == actor.user_id,
            m.Referral.created_at > now - dt.timedelta(hours=24),
        )
    )
    if (today or 0) >= DAILY_LIMIT:
        raise Conflict(
            "You have raised a lot of referrals today. Please talk to the wellbeing team."
        )

    referral = m.Referral(
        id=uuid7(),
        institution_id=actor.institution_id,
        teacher_id=actor.user_id,
        student_id=student_id,
        course_id=course_id,
        category=category,
        urgency=urgency,
        note=text,
        status=ReferralStatus.RECEIVED,
    )
    db.add(referral)
    try:
        await db.flush()
    except IntegrityError as exc:  # the one-live-referral index caught a double submit
        await db.rollback()
        raise Conflict("You already have an open referral for this student.") from exc

    if category is ReferralCategory.SAFETY_CONCERN:
        await raise_alert(
            db,
            institution_id=actor.institution_id,
            student_id=student_id,
            source=AlertSource.FACULTY_REFERRAL,
            detector=AlertDetector.HUMAN,
            category=AlertCategory.UNSAFE_SITUATION,
            severity=AlertSeverity.HIGH,
            title="A teacher has raised a safety concern",
            now=now,
            source_type="referral",
            source_id=referral.id,
        )
    await teacher_audit(
        db,
        actor,
        "referral.create",
        "referral",
        referral.id,
        subject_student_id=student_id,
        category=category.value,
        urgency=urgency.value,
        has_note=text is not None,
    )
    await db.commit()
    return await _teacher_view(db, referral)


async def _teacher_view(db: AsyncSession, referral: m.Referral) -> ReferralView:
    rows = await _teacher_rows(db, m.Referral.id == referral.id)
    return rows[0]


async def _teacher_rows(db: AsyncSession, *where: ColumnElement[bool]) -> list[ReferralView]:
    rows = (
        await db.execute(
            select(
                m.Referral,
                m.Student.preferred_name,
                m.User.full_name,
                m.Course.code,
                m.Course.title,
            )
            .join(m.User, m.User.id == m.Referral.student_id)
            .join(m.Student, m.Student.user_id == m.Referral.student_id)
            .join(m.Course, m.Course.id == m.Referral.course_id)
            .where(*where)
            .order_by(m.Referral.created_at.desc())
            .limit(100)
        )
    ).all()
    return [ReferralView(r, _display(p, f), code, title) for r, p, f, code, title in rows]


async def list_mine(
    db: AsyncSession, actor: Principal, status: ReferralStatus | None
) -> list[ReferralView]:
    where: list[ColumnElement[bool]] = [
        m.Referral.teacher_id == actor.user_id,
        m.Referral.institution_id == actor.institution_id,
    ]
    if status is not None:
        where.append(m.Referral.status == status)
    rows = await _teacher_rows(db, *where)
    await teacher_audit(db, actor, "referral.list", "referral", count=len(rows))
    await db.commit()
    return rows


async def get_mine(db: AsyncSession, actor: Principal, referral_id: uuid.UUID) -> ReferralView:
    rows = await _teacher_rows(
        db, m.Referral.id == referral_id, m.Referral.institution_id == actor.institution_id
    )
    if not rows:
        raise NotFound
    row = rows[0]
    enforce(
        can_manage_own_teacher_record(
            actor,
            record_institution_id=row.referral.institution_id,
            record_teacher_id=row.referral.teacher_id,
        ),
        action="referral.read",
        resource_type="referral",
        resource_id=referral_id,
        subject_student_id=row.referral.student_id,
    )
    await teacher_audit(
        db,
        actor,
        "referral.read",
        "referral",
        referral_id,
        subject_student_id=row.referral.student_id,
    )
    await db.commit()
    return row


# ---- therapist side -------------------------------------------------------------------------


def _active_link(
    student_id: object, now: dt.datetime, therapist_id: uuid.UUID | None = None
) -> ColumnElement[bool]:
    where = [
        m.CareTeamMember.student_id == student_id,
        m.CareTeamMember.starts_at <= now,
        or_(m.CareTeamMember.ends_at.is_(None), m.CareTeamMember.ends_at > now),
    ]
    if therapist_id is not None:
        where.append(m.CareTeamMember.therapist_id == therapist_id)
    return exists().where(*where)


async def _triage_rows(
    db: AsyncSession, actor: Principal, now: dt.datetime, *where: ColumnElement[bool]
) -> list[TriageView]:
    teacher_user = m.User.__table__.alias("teacher_user")
    mine = _active_link(m.Referral.student_id, now, actor.user_id)
    anyone = _active_link(m.Referral.student_id, now)
    rows = (
        await db.execute(
            select(
                m.Referral,
                m.Student.preferred_name,
                m.User.full_name,
                m.Course.code,
                m.Course.title,
                teacher_user.c.full_name,
                m.Department.name,
                mine,
            )
            .join(m.User, m.User.id == m.Referral.student_id)
            .join(m.Student, m.Student.user_id == m.Referral.student_id)
            .join(m.Course, m.Course.id == m.Referral.course_id)
            .join(teacher_user, teacher_user.c.id == m.Referral.teacher_id)
            .join(
                m.Department,
                (m.Department.id == m.Student.department_id)
                & (m.Department.institution_id == m.Student.institution_id),
            )
            .where(
                m.Referral.institution_id == actor.institution_id,
                or_(mine, ~anyone),
                or_(m.Referral.claimed_by.is_(None), m.Referral.claimed_by == actor.user_id),
                *where,
            )
            .order_by(
                case(URGENCY_RANK, value=m.Referral.urgency),
                m.Referral.created_at,
            )
            .limit(200)
        )
    ).all()
    return [
        TriageView(r, _display(p, f), code, title, tname, dept, bool(is_mine))
        for r, p, f, code, title, tname, dept, is_mine in rows
    ]


async def queue(
    db: AsyncSession, actor: Principal, status: ReferralStatus | None
) -> list[TriageView]:
    await require_verified(db, actor, "referral.list")
    now = now_utc()
    where: list[ColumnElement[bool]] = []
    if status is not None:
        where.append(m.Referral.status == status)
    else:
        where.append(m.Referral.status != ReferralStatus.CLOSED)
    rows = await _triage_rows(db, actor, now, *where)
    await _therapist_audit(db, actor, "referral.list", None, None, count=len(rows))
    await db.commit()
    return rows


async def _therapist_audit(
    db: AsyncSession,
    actor: Principal,
    action: str,
    referral_id: uuid.UUID | None,
    student_id: uuid.UUID | None,
    **details: object,
) -> None:
    await append_audit_event(
        db,
        institution_id=actor.institution_id,
        actor_id=actor.user_id,
        actor_role=UserRole.THERAPIST,
        action=action,
        outcome=AuditOutcome.ALLOWED,
        resource_type="referral",
        resource_id=referral_id,
        subject_student_id=student_id,
        details=dict(details),
    )


async def _triage_one(
    db: AsyncSession, actor: Principal, referral_id: uuid.UUID, action: str
) -> TriageView:
    therapist = await require_verified(db, actor, action)
    now = now_utc()
    referral = await db.get(m.Referral, referral_id)
    if referral is None:
        raise NotFound
    mine = await db.scalar(select(_active_link(referral.student_id, now, actor.user_id)))
    anyone = await db.scalar(select(_active_link(referral.student_id, now)))
    decision = can_triage_referral(
        actor,
        referral_institution_id=referral.institution_id,
        is_verified=therapist is not None,
        on_care_team=bool(mine),
        student_has_care_team=bool(anyone),
    )
    if decision.allowed and referral.claimed_by not in (None, actor.user_id):
        decision = deny("claimed_by_someone_else", hide=True)
    enforce(
        decision,
        action=action,
        resource_type="referral",
        resource_id=referral_id,
        subject_student_id=referral.student_id,
    )
    rows = await _triage_rows(db, actor, now, m.Referral.id == referral_id)
    if not rows:
        raise NotFound
    return rows[0]


async def get_for_triage(db: AsyncSession, actor: Principal, referral_id: uuid.UUID) -> TriageView:
    view = await _triage_one(db, actor, referral_id, "referral.read")
    await _therapist_audit(
        db,
        actor,
        "referral.read",
        referral_id,
        view.referral.student_id,
        category=view.referral.category.value,
    )
    await db.commit()
    return view


async def claim(db: AsyncSession, actor: Principal, referral_id: uuid.UUID) -> TriageView:
    view = await _triage_one(db, actor, referral_id, "referral.claim")
    referral = await db.get(m.Referral, referral_id, with_for_update=True)
    assert referral is not None
    if referral.status is not ReferralStatus.RECEIVED:
        raise InvalidTransition("This referral has already been picked up.")
    now = now_utc()
    referral.status = ReferralStatus.IN_PROGRESS
    referral.claimed_by = actor.user_id
    referral.claimed_at = now
    await notify(
        db,
        institution_id=actor.institution_id,
        user_id=referral.student_id,
        type=NotificationType.SYSTEM,
        priority=NotificationPriority.NORMAL,
        title="The wellbeing team would like to check in",
        payload={},
    )
    await _therapist_audit(db, actor, "referral.claim", referral_id, referral.student_id)
    await db.commit()
    return dataclasses.replace(view, referral=referral)


async def close(
    db: AsyncSession, actor: Principal, referral_id: uuid.UUID, outcome: ReferralOutcome
) -> TriageView:
    view = await _triage_one(db, actor, referral_id, "referral.close")
    referral = await db.get(m.Referral, referral_id, with_for_update=True)
    assert referral is not None
    if referral.status is not ReferralStatus.IN_PROGRESS or referral.claimed_by != actor.user_id:
        raise InvalidTransition("Only the person who picked this referral up can close it.")
    referral.status = ReferralStatus.CLOSED
    referral.closed_at = now_utc()
    referral.outcome = outcome
    await _therapist_audit(
        db, actor, "referral.close", referral_id, referral.student_id, outcome=outcome.value
    )
    await db.commit()
    return dataclasses.replace(view, referral=referral)
