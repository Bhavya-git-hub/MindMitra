"""The teacher portal: classes, privacy-preserving group figures, roster and faculty resources.

What a teacher can learn here is limited by three things, each enforced in this module and
again by the route guard:

* **Scope.** Figures exist only for a class the teacher teaches or the teacher's own department;
  anything else is refused (404 for another teacher's class so its existence is not revealed,
  403 for another department).
* **Opt-in.** Only students who have an active anonymous-aggregate consent are counted at all.
* **Thresholds.** ``domain.wellness.cohort`` withholds or coarsens every figure that could point
  at one student.

No individual's mood, journal, assessment, message, note or conversation is read by anything
here. The roster is names only: the teacher already knows who is in their class.
"""

import dataclasses
import datetime as dt
import uuid
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application import cohort_stats
from app.application.access import NotFound, enforce
from app.application.errors import InvalidInput
from app.application.timeutil import now_utc
from app.domain.auth.policies import (
    Principal,
    can_view_class_analytics,
    can_view_department_analytics,
)
from app.domain.wellness import cohort
from app.infrastructure.db import models as m
from app.infrastructure.db.audit import append_audit_event
from app.infrastructure.db.enums import (
    AuditOutcome,
    EnrollmentStatus,
    ReferralStatus,
    TeacherSupportStatus,
    UserRole,
)

DEFAULT_WEEKS = 8


@dataclasses.dataclass
class TeacherContext:
    teacher: m.Teacher
    name: str
    department: m.Department


@dataclasses.dataclass
class ClassInfo:
    course: m.Course
    department_name: str
    enrolled: int


@dataclasses.dataclass
class RosterRow:
    student_id: uuid.UUID
    name: str


@dataclasses.dataclass
class GroupView:
    """A group's figures plus the words that say which group and window they describe."""

    label: str
    scope: str  # "class" or "department"
    weeks: int
    figures: cohort_stats.GroupFigures
    generated_at: dt.datetime


@dataclasses.dataclass
class Dashboard:
    context: TeacherContext
    classes: list[ClassInfo]
    department: GroupView
    referrals_by_status: dict[ReferralStatus, int]
    open_support_requests: int
    unread_support_requests: int


def check_weeks(weeks: int | None) -> int:
    chosen = DEFAULT_WEEKS if weeks is None else weeks
    if chosen not in cohort.ALLOWED_WEEKS:
        allowed = ", ".join(str(w) for w in cohort.ALLOWED_WEEKS)
        raise InvalidInput(f"Choose a window of {allowed} weeks.")
    return chosen


async def own_context(db: AsyncSession, actor: Principal) -> TeacherContext:
    row = (
        await db.execute(
            select(m.Teacher, m.User.full_name, m.Department)
            .join(m.User, m.User.id == m.Teacher.user_id)
            .join(
                m.Department,
                (m.Department.id == m.Teacher.department_id)
                & (m.Department.institution_id == m.Teacher.institution_id),
            )
            .where(
                m.Teacher.user_id == actor.user_id,
                m.Teacher.institution_id == actor.institution_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise NotFound
    return TeacherContext(row[0], row[1], row[2])


async def audit(
    db: AsyncSession,
    actor: Principal,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None = None,
    subject_student_id: uuid.UUID | None = None,
    **details: object,
) -> None:
    """Record a teacher's read or action. Metadata only; never figures, names or text."""
    await append_audit_event(
        db,
        institution_id=actor.institution_id,
        actor_id=actor.user_id,
        actor_role=UserRole.TEACHER,
        action=action,
        outcome=AuditOutcome.ALLOWED,
        resource_type=resource_type,
        resource_id=resource_id,
        subject_student_id=subject_student_id,
        details=dict(details),
    )


# ---- classes --------------------------------------------------------------------------------


def _taught_by(teacher_id: uuid.UUID, institution_id: uuid.UUID) -> Any:
    return (
        select(m.CourseTeacher.course_id)
        .where(
            m.CourseTeacher.teacher_id == teacher_id,
            m.CourseTeacher.institution_id == institution_id,
        )
        .scalar_subquery()
    )


async def _enrolled_counts(db: AsyncSession, course_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not course_ids:
        return {}
    rows = await db.execute(
        select(m.CourseEnrollment.course_id, func.count())
        .where(
            m.CourseEnrollment.course_id.in_(course_ids),
            m.CourseEnrollment.status == EnrollmentStatus.ENROLLED,
        )
        .group_by(m.CourseEnrollment.course_id)
    )
    return {cid: n for cid, n in rows}


async def list_classes(db: AsyncSession, actor: Principal) -> list[ClassInfo]:
    rows = (
        await db.execute(
            select(m.Course, m.Department.name)
            .join(
                m.Department,
                (m.Department.id == m.Course.department_id)
                & (m.Department.institution_id == m.Course.institution_id),
            )
            .where(
                m.Course.institution_id == actor.institution_id,
                m.Course.id.in_(_taught_by(actor.user_id, actor.institution_id)),
            )
            .order_by(m.Course.term.desc(), m.Course.code)
        )
    ).all()
    counts = await _enrolled_counts(db, [c.id for c, _ in rows])
    return [ClassInfo(c, dept, counts.get(c.id, 0)) for c, dept in rows]


async def _own_class(
    db: AsyncSession, actor: Principal, course_id: uuid.UUID, action: str
) -> ClassInfo:
    """The class, once policy says the actor teaches it. Unknown and not-mine look the same."""
    row = (
        await db.execute(
            select(m.Course, m.Department.name)
            .join(
                m.Department,
                (m.Department.id == m.Course.department_id)
                & (m.Department.institution_id == m.Course.institution_id),
            )
            .where(m.Course.id == course_id)
        )
    ).one_or_none()
    if row is None:
        raise NotFound
    course, dept_name = row
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
    enforce(
        can_view_class_analytics(
            actor, course_institution_id=course.institution_id, teaches_course=teaches
        ),
        action=action,
        resource_type="course",
        resource_id=course_id,
    )
    counts = await _enrolled_counts(db, [course_id])
    return ClassInfo(course, dept_name, counts.get(course_id, 0))


async def get_class(db: AsyncSession, actor: Principal, course_id: uuid.UUID) -> ClassInfo:
    return await _own_class(db, actor, course_id, "class.read")


def _enrolled_ids(course_id: uuid.UUID) -> Select[Any]:
    return select(m.CourseEnrollment.student_id).where(
        m.CourseEnrollment.course_id == course_id,
        m.CourseEnrollment.status == EnrollmentStatus.ENROLLED,
    )


async def roster(db: AsyncSession, actor: Principal, course_id: uuid.UUID) -> list[RosterRow]:
    """Names of the students enrolled in the teacher's class, and nothing else about them."""
    await _own_class(db, actor, course_id, "class.roster")
    rows = (
        await db.execute(
            select(m.Student.user_id, m.Student.preferred_name, m.User.full_name)
            .join(m.User, m.User.id == m.Student.user_id)
            .where(
                m.Student.user_id.in_(_enrolled_ids(course_id)),
                m.Student.institution_id == actor.institution_id,
                m.User.deleted_at.is_(None),
            )
            .order_by(m.User.full_name)
        )
    ).all()
    await audit(db, actor, "class.roster", "course", course_id, count=len(rows))
    await db.commit()
    return [RosterRow(sid, preferred or full) for sid, preferred, full in rows]


# ---- group figures --------------------------------------------------------------------------


async def class_view(
    db: AsyncSession, actor: Principal, course_id: uuid.UUID, weeks: int | None
) -> tuple[ClassInfo, GroupView]:
    chosen = check_weeks(weeks)
    info = await _own_class(db, actor, course_id, "class_analytics.read")
    figures = await cohort_stats.figures(db, actor.institution_id, _enrolled_ids(course_id), chosen)
    await audit(
        db,
        actor,
        "class_analytics.read",
        "course",
        course_id,
        weeks=chosen,
        result=figures.analytics.state,
    )
    await db.commit()
    label = f"{info.course.code} {info.course.title}"
    return info, GroupView(label, "class", chosen, figures, now_utc())


async def department_view(
    db: AsyncSession, actor: Principal, department_id: uuid.UUID, weeks: int | None
) -> tuple[m.Department, GroupView]:
    chosen = check_weeks(weeks)
    ctx = await own_context(db, actor)
    dept = await db.get(m.Department, department_id)
    if dept is None:
        raise NotFound
    enforce(
        can_view_department_analytics(
            actor,
            department_institution_id=dept.institution_id,
            department_id=dept.id,
            teacher_department_id=ctx.teacher.department_id,
        ),
        action="department_analytics.read",
        resource_type="department",
        resource_id=department_id,
    )
    members = select(m.Student.user_id).where(
        m.Student.department_id == department_id,
        m.Student.institution_id == actor.institution_id,
    )
    figures = await cohort_stats.figures(db, actor.institution_id, members, chosen)
    await audit(
        db,
        actor,
        "department_analytics.read",
        "department",
        department_id,
        weeks=chosen,
        result=figures.analytics.state,
    )
    await db.commit()
    return dept, GroupView(dept.name, "department", chosen, figures, now_utc())


# ---- dashboard ------------------------------------------------------------------------------


async def dashboard(db: AsyncSession, actor: Principal) -> Dashboard:
    ctx = await own_context(db, actor)
    classes = await list_classes(db, actor)
    _, department = await department_view(db, actor, ctx.department.id, 4)

    by_status = {s: 0 for s in ReferralStatus}
    for status, n in await db.execute(
        select(m.Referral.status, func.count())
        .where(m.Referral.teacher_id == actor.user_id)
        .group_by(m.Referral.status)
    ):
        by_status[status] = n
    live = (TeacherSupportStatus.OPEN, TeacherSupportStatus.ACKNOWLEDGED)
    open_requests = (
        await db.scalar(
            select(func.count())
            .select_from(m.TeacherSupportRequest)
            .where(
                m.TeacherSupportRequest.teacher_id == actor.user_id,
                m.TeacherSupportRequest.status.in_(live),
            )
        )
        or 0
    )
    new_requests = (
        await db.scalar(
            select(func.count())
            .select_from(m.TeacherSupportRequest)
            .where(
                m.TeacherSupportRequest.teacher_id == actor.user_id,
                m.TeacherSupportRequest.status == TeacherSupportStatus.OPEN,
            )
        )
        or 0
    )
    return Dashboard(ctx, classes, department, by_status, open_requests, new_requests)
