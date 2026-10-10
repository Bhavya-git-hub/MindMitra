"""Support requests a student sends to one of their own teachers.

This is the other direction from a referral: here the student decides. They pick the course and
the teacher (only people who teach a course they are enrolled in), choose a topic, and may add a
short message. The teacher sees that message and the student's name because the student chose to
send it. Nothing else about the student comes with it, and the student can withdraw it.
"""

import dataclasses
import datetime as dt
import uuid

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.access import NotFound, enforce
from app.application.auth.errors import Conflict
from app.application.care import InvalidTransition
from app.application.errors import InvalidInput
from app.application.student_wellness import authorize_own
from app.application.teacher_portal import audit as teacher_audit
from app.application.timeutil import now_utc
from app.domain.auth.policies import Principal, can_manage_own_teacher_record
from app.infrastructure.db import models as m
from app.infrastructure.db.audit import append_audit_event
from app.infrastructure.db.enums import (
    AuditOutcome,
    EnrollmentStatus,
    NotificationType,
    TeacherSupportStatus,
    TeacherSupportTopic,
    UserRole,
)
from app.infrastructure.db.ids import uuid7

MAX_MESSAGE = 600
DAILY_LIMIT = 5
LIVE = (TeacherSupportStatus.OPEN, TeacherSupportStatus.ACKNOWLEDGED)


@dataclasses.dataclass
class TeacherOption:
    teacher_id: uuid.UUID
    name: str
    title: str | None


@dataclasses.dataclass
class CourseOption:
    course_id: uuid.UUID
    code: str
    title: str
    teachers: list[TeacherOption]


@dataclasses.dataclass
class RequestView:
    request: m.TeacherSupportRequest
    course_code: str
    course_title: str
    teacher_name: str
    student_name: str


# ---- student side ---------------------------------------------------------------------------


async def my_courses(db: AsyncSession, actor: Principal) -> list[CourseOption]:
    """The student's own courses and who teaches each, so they can choose who to ask."""
    authorize_own(db, actor, "teacher_support.options", "teacher_support_request")
    rows = (
        await db.execute(
            select(m.Course, m.Teacher.user_id, m.User.full_name, m.Teacher.title)
            .join(m.CourseEnrollment, m.CourseEnrollment.course_id == m.Course.id)
            .join(m.CourseTeacher, m.CourseTeacher.course_id == m.Course.id)
            .join(m.Teacher, m.Teacher.user_id == m.CourseTeacher.teacher_id)
            .join(m.User, m.User.id == m.Teacher.user_id)
            .where(
                m.CourseEnrollment.student_id == actor.user_id,
                m.CourseEnrollment.status == EnrollmentStatus.ENROLLED,
                m.Course.institution_id == actor.institution_id,
                m.User.deleted_at.is_(None),
            )
            .order_by(m.Course.code, m.User.full_name)
        )
    ).all()
    by_course: dict[uuid.UUID, CourseOption] = {}
    for course, teacher_id, name, title in rows:
        option = by_course.setdefault(
            course.id, CourseOption(course.id, course.code, course.title, [])
        )
        option.teachers.append(TeacherOption(teacher_id, name, title))
    return list(by_course.values())


async def create(
    db: AsyncSession,
    actor: Principal,
    *,
    course_id: uuid.UUID,
    teacher_id: uuid.UUID,
    topic: TeacherSupportTopic,
    message: str | None,
) -> RequestView:
    authorize_own(db, actor, "teacher_support.create", "teacher_support_request")
    text = (message or "").strip() or None
    if text and len(text) > MAX_MESSAGE:
        raise InvalidInput(f"Please keep your message under {MAX_MESSAGE} characters.")

    # The student must be enrolled and the teacher must teach the course. Anything else is
    # reported as "not found" so a student cannot probe who teaches what.
    enrolled = await db.scalar(
        select(func.count())
        .select_from(m.CourseEnrollment)
        .where(
            m.CourseEnrollment.course_id == course_id,
            m.CourseEnrollment.student_id == actor.user_id,
            m.CourseEnrollment.status == EnrollmentStatus.ENROLLED,
        )
    )
    teaches = await db.scalar(
        select(func.count())
        .select_from(m.CourseTeacher)
        .where(m.CourseTeacher.course_id == course_id, m.CourseTeacher.teacher_id == teacher_id)
    )
    if not enrolled or not teaches:
        raise NotFound

    now = now_utc()
    recent = await db.scalar(
        select(func.count())
        .select_from(m.TeacherSupportRequest)
        .where(
            m.TeacherSupportRequest.student_id == actor.user_id,
            m.TeacherSupportRequest.created_at > now - dt.timedelta(hours=24),
        )
    )
    if (recent or 0) >= DAILY_LIMIT:
        raise Conflict(
            "You have sent several requests today. Please give your teachers time to reply."
        )

    request = m.TeacherSupportRequest(
        id=uuid7(),
        institution_id=actor.institution_id,
        student_id=actor.user_id,
        teacher_id=teacher_id,
        course_id=course_id,
        topic=topic,
        message=text,
        status=TeacherSupportStatus.OPEN,
    )
    db.add(request)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict(
            "You already have an open request with this teacher for this course."
        ) from exc
    db.add(
        m.Notification(
            id=uuid7(),
            institution_id=actor.institution_id,
            user_id=teacher_id,
            type=NotificationType.SYSTEM,
            title="A student has asked for your help",
            payload={"request_id": str(request.id)},
        )
    )
    await _audit(
        db, actor, UserRole.STUDENT, "teacher_support.create", request.id, actor.user_id,
        topic=topic.value, has_message=text is not None,
    )  # fmt: skip
    await db.commit()
    return (await _views(db, m.TeacherSupportRequest.id == request.id))[0]


async def list_mine(db: AsyncSession, actor: Principal) -> list[RequestView]:
    authorize_own(db, actor, "teacher_support.list", "teacher_support_request")
    return await _views(db, m.TeacherSupportRequest.student_id == actor.user_id)


async def withdraw(db: AsyncSession, actor: Principal, request_id: uuid.UUID) -> RequestView:
    authorize_own(db, actor, "teacher_support.withdraw", "teacher_support_request")
    request = await db.get(m.TeacherSupportRequest, request_id, with_for_update=True)
    if request is None or request.student_id != actor.user_id:
        raise NotFound
    if request.status not in LIVE:
        raise InvalidTransition("This request is already closed.")
    request.status = TeacherSupportStatus.WITHDRAWN
    request.closed_at = now_utc()
    await _audit(db, actor, UserRole.STUDENT, "teacher_support.withdraw", request_id, actor.user_id)
    await db.commit()
    return (await _views(db, m.TeacherSupportRequest.id == request_id))[0]


# ---- teacher side ---------------------------------------------------------------------------


async def list_for_teacher(
    db: AsyncSession, actor: Principal, status: TeacherSupportStatus | None
) -> list[RequestView]:
    where: list[ColumnElement[bool]] = [
        m.TeacherSupportRequest.teacher_id == actor.user_id,
        m.TeacherSupportRequest.institution_id == actor.institution_id,
    ]
    if status is not None:
        where.append(m.TeacherSupportRequest.status == status)
    else:
        where.append(m.TeacherSupportRequest.status.in_(LIVE))
    rows = await _views(db, *where)
    await teacher_audit(
        db, actor, "teacher_support.list", "teacher_support_request", count=len(rows)
    )
    await db.commit()
    return rows


async def _own_request(
    db: AsyncSession, actor: Principal, request_id: uuid.UUID, action: str
) -> m.TeacherSupportRequest:
    request = await db.get(m.TeacherSupportRequest, request_id, with_for_update=True)
    if request is None:
        raise NotFound
    enforce(
        can_manage_own_teacher_record(
            actor,
            record_institution_id=request.institution_id,
            record_teacher_id=request.teacher_id,
        ),
        action=action,
        resource_type="teacher_support_request",
        resource_id=request_id,
        subject_student_id=request.student_id,
    )
    return request


async def acknowledge(db: AsyncSession, actor: Principal, request_id: uuid.UUID) -> RequestView:
    request = await _own_request(db, actor, request_id, "teacher_support.acknowledge")
    if request.status is not TeacherSupportStatus.OPEN:
        raise InvalidTransition("This request has already been seen.")
    request.status = TeacherSupportStatus.ACKNOWLEDGED
    request.acknowledged_at = now_utc()
    db.add(
        m.Notification(
            id=uuid7(),
            institution_id=actor.institution_id,
            user_id=request.student_id,
            type=NotificationType.SYSTEM,
            title="Your teacher has seen your request",
            payload={"request_id": str(request.id)},
        )
    )
    await teacher_audit(
        db,
        actor,
        "teacher_support.acknowledge",
        "teacher_support_request",
        request_id,
        request.student_id,
    )
    await db.commit()
    return (await _views(db, m.TeacherSupportRequest.id == request_id))[0]


async def close(db: AsyncSession, actor: Principal, request_id: uuid.UUID) -> RequestView:
    request = await _own_request(db, actor, request_id, "teacher_support.close")
    if request.status not in LIVE:
        raise InvalidTransition("This request is already closed.")
    request.status = TeacherSupportStatus.CLOSED
    request.closed_at = now_utc()
    await teacher_audit(
        db,
        actor,
        "teacher_support.close",
        "teacher_support_request",
        request_id,
        request.student_id,
    )
    await db.commit()
    return (await _views(db, m.TeacherSupportRequest.id == request_id))[0]


# ---- shared ---------------------------------------------------------------------------------


async def _audit(
    db: AsyncSession,
    actor: Principal,
    role: UserRole,
    action: str,
    request_id: uuid.UUID,
    student_id: uuid.UUID,
    **details: object,
) -> None:
    await append_audit_event(
        db,
        institution_id=actor.institution_id,
        actor_id=actor.user_id,
        actor_role=role,
        action=action,
        outcome=AuditOutcome.ALLOWED,
        resource_type="teacher_support_request",
        resource_id=request_id,
        subject_student_id=student_id,
        details=dict(details),
    )


async def _views(db: AsyncSession, *where: ColumnElement[bool]) -> list[RequestView]:
    teacher_user = m.User.__table__.alias("teacher_user")
    rows = (
        await db.execute(
            select(
                m.TeacherSupportRequest,
                m.Course.code,
                m.Course.title,
                teacher_user.c.full_name,
                m.Student.preferred_name,
                m.User.full_name,
            )
            .join(m.Course, m.Course.id == m.TeacherSupportRequest.course_id)
            .join(teacher_user, teacher_user.c.id == m.TeacherSupportRequest.teacher_id)
            .join(m.Student, m.Student.user_id == m.TeacherSupportRequest.student_id)
            .join(m.User, m.User.id == m.TeacherSupportRequest.student_id)
            .where(*where)
            .order_by(m.TeacherSupportRequest.created_at.desc())
            .limit(100)
        )
    ).all()
    return [
        RequestView(r, code, title, tname, preferred or full)
        for r, code, title, tname, preferred, full in rows
    ]
