"""Administrator use cases for the institution's people and academic structure.

Students, teachers and therapists (account details and role profiles), departments, courses,
who teaches a course and who is enrolled. All of it is registrar-style data. Nothing here reads
or returns wellbeing, conversation, journal, therapy or alert content, and care-team membership
is deliberately left out so an administrator cannot tell who is in therapy.

Every change that can move a group's membership (department, enrolment, account status) forgets
the stored figures for the groups involved, so a withdrawal or move takes effect at once.
"""

import dataclasses
import re
import uuid

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application import cohort_stats
from app.application.access import NotFound, enforce
from app.application.admin_common import LIKE_ESCAPE, MAX_LIMIT, audit, count, like
from app.application.auth.errors import Conflict
from app.application.errors import InvalidInput
from app.domain.auth.policies import Principal, can_administer
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import EnrollmentStatus, UserStatus, VerificationStatus
from app.infrastructure.db.ids import uuid7

CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{0,19}$")
COURSE_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9 -]{0,19}$")
TERM_RE = re.compile(r"^[0-9]{4}-[a-z]{3,10}$")


def _clean(value: str, what: str, limit: int) -> str:
    text = " ".join(value.split())
    if not text:
        raise InvalidInput(f"{what} cannot be empty.")
    if len(text) > limit:
        raise InvalidInput(f"{what} must be at most {limit} characters.")
    return text


def _code(value: str, pattern: re.Pattern[str], what: str) -> str:
    code = value.strip().upper()
    if not pattern.match(code):
        raise InvalidInput(f"{what} may use letters, digits and hyphens only.")
    return code


# ---- departments -----------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class DepartmentRow:
    department: m.Department
    students: int
    teachers: int
    courses: int


async def _department(
    db: AsyncSession, actor: Principal, department_id: uuid.UUID, action: str
) -> m.Department:
    dept = await db.get(m.Department, department_id)
    if dept is None:
        raise NotFound
    enforce(
        can_administer(actor, institution_id=dept.institution_id),
        action=action,
        resource_type="department",
        resource_id=department_id,
    )
    return dept


async def list_departments(db: AsyncSession, actor: Principal) -> list[DepartmentRow]:
    rows: list[DepartmentRow] = []
    for dept in await db.scalars(
        select(m.Department)
        .where(m.Department.institution_id == actor.institution_id)
        .order_by(m.Department.name)
    ):
        rows.append(
            DepartmentRow(
                dept,
                await count(
                    db,
                    select(func.count())
                    .select_from(m.Student)
                    .where(m.Student.department_id == dept.id),
                ),
                await count(
                    db,
                    select(func.count())
                    .select_from(m.Teacher)
                    .where(m.Teacher.department_id == dept.id),
                ),
                await count(
                    db,
                    select(func.count())
                    .select_from(m.Course)
                    .where(m.Course.department_id == dept.id),
                ),
            )
        )
    return rows


async def create_department(
    db: AsyncSession, actor: Principal, *, name: str, code: str
) -> m.Department:
    dept = m.Department(
        id=uuid7(),
        institution_id=actor.institution_id,
        name=_clean(name, "The name", 200),
        code=_code(code, CODE_RE, "The code"),
    )
    db.add(dept)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict("A department with this code already exists.") from exc
    await audit(db, actor, "department.create", resource_type="department", resource_id=dept.id)
    await db.commit()
    return dept


async def update_department(
    db: AsyncSession,
    actor: Principal,
    department_id: uuid.UUID,
    *,
    name: str | None,
    code: str | None,
) -> m.Department:
    dept = await _department(db, actor, department_id, "department.update")
    changed: list[str] = []
    if name is not None:
        dept.name = _clean(name, "The name", 200)
        changed.append("name")
    if code is not None:
        dept.code = _code(code, CODE_RE, "The code")
        changed.append("code")
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict("A department with this code already exists.") from exc
    await audit(
        db,
        actor,
        "department.update",
        resource_type="department",
        resource_id=dept.id,
        fields=",".join(changed),
    )
    await db.commit()
    return dept


async def delete_department(db: AsyncSession, actor: Principal, department_id: uuid.UUID) -> None:
    dept = await _department(db, actor, department_id, "department.delete")
    in_use = (
        await count(
            db,
            select(func.count()).select_from(m.Student).where(m.Student.department_id == dept.id),
        )
        + await count(
            db,
            select(func.count()).select_from(m.Teacher).where(m.Teacher.department_id == dept.id),
        )
        + await count(
            db,
            select(func.count()).select_from(m.Course).where(m.Course.department_id == dept.id),
        )
    )
    if in_use:
        raise Conflict("Move or remove this department's students, teachers and courses first.")
    await db.execute(
        delete(m.GroupSnapshot).where(
            m.GroupSnapshot.institution_id == actor.institution_id,
            m.GroupSnapshot.group_kind == "department",
            m.GroupSnapshot.group_id == dept.id,
        )
    )
    await db.delete(dept)
    await audit(db, actor, "department.delete", resource_type="department", resource_id=dept.id)
    await db.commit()


# ---- courses ---------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class CourseRow:
    course: m.Course
    department: m.Department
    teachers: int
    enrolled: int


@dataclasses.dataclass(frozen=True)
class Person:
    user_id: uuid.UUID
    full_name: str
    number: str  # student number or employee number


@dataclasses.dataclass(frozen=True)
class CourseDetail:
    row: CourseRow
    teachers: list[Person]
    students: list[Person]


async def _course(
    db: AsyncSession, actor: Principal, course_id: uuid.UUID, action: str
) -> m.Course:
    course = await db.get(m.Course, course_id)
    if course is None:
        raise NotFound
    enforce(
        can_administer(actor, institution_id=course.institution_id),
        action=action,
        resource_type="course",
        resource_id=course_id,
    )
    return course


async def _course_row(db: AsyncSession, course: m.Course) -> CourseRow:
    dept = await db.get(m.Department, course.department_id)
    if dept is None:  # the foreign key makes this unreachable
        raise NotFound
    teachers = await count(
        db,
        select(func.count())
        .select_from(m.CourseTeacher)
        .where(m.CourseTeacher.course_id == course.id),
    )
    enrolled = await count(
        db,
        select(func.count())
        .select_from(m.CourseEnrollment)
        .where(
            m.CourseEnrollment.course_id == course.id,
            m.CourseEnrollment.status == EnrollmentStatus.ENROLLED,
        ),
    )
    return CourseRow(course, dept, teachers, enrolled)


async def list_courses(
    db: AsyncSession,
    actor: Principal,
    *,
    department_id: uuid.UUID | None,
    term: str | None,
    query: str | None,
) -> list[CourseRow]:
    stmt = select(m.Course).where(m.Course.institution_id == actor.institution_id)
    if department_id is not None:
        stmt = stmt.where(m.Course.department_id == department_id)
    if term:
        stmt = stmt.where(m.Course.term == term)
    if query and query.strip():
        pattern = like(query)
        stmt = stmt.where(
            or_(
                m.Course.code.ilike(pattern, escape=LIKE_ESCAPE),
                m.Course.title.ilike(pattern, escape=LIKE_ESCAPE),
            )
        )
    courses = await db.scalars(stmt.order_by(m.Course.term.desc(), m.Course.code).limit(MAX_LIMIT))
    return [await _course_row(db, c) for c in courses]


async def course_detail(db: AsyncSession, actor: Principal, course_id: uuid.UUID) -> CourseDetail:
    course = await _course(db, actor, course_id, "course.read")
    teachers = (
        await db.execute(
            select(m.Teacher.user_id, m.User.full_name, m.Teacher.employee_number)
            .join(m.CourseTeacher, m.CourseTeacher.teacher_id == m.Teacher.user_id)
            .join(m.User, m.User.id == m.Teacher.user_id)
            .where(m.CourseTeacher.course_id == course_id)
            .order_by(m.User.full_name)
        )
    ).all()
    students = (
        await db.execute(
            select(m.Student.user_id, m.User.full_name, m.Student.student_number)
            .join(m.CourseEnrollment, m.CourseEnrollment.student_id == m.Student.user_id)
            .join(m.User, m.User.id == m.Student.user_id)
            .where(
                m.CourseEnrollment.course_id == course_id,
                m.CourseEnrollment.status == EnrollmentStatus.ENROLLED,
            )
            .order_by(m.User.full_name)
            .limit(500)
        )
    ).all()
    return CourseDetail(
        await _course_row(db, course),
        [Person(*r) for r in teachers],
        [Person(*r) for r in students],
    )


def _term(value: str) -> str:
    term = value.strip().lower()
    if not TERM_RE.match(term):
        raise InvalidInput("Use a term like 2026-autumn.")
    return term


async def create_course(
    db: AsyncSession,
    actor: Principal,
    *,
    department_id: uuid.UUID,
    code: str,
    title: str,
    term: str,
    credits: int,
) -> CourseRow:
    await _department(db, actor, department_id, "course.create")
    if not 0 <= credits <= 30:
        raise InvalidInput("Credits must be between 0 and 30.")
    course = m.Course(
        id=uuid7(),
        institution_id=actor.institution_id,
        department_id=department_id,
        code=_code(code, COURSE_CODE_RE, "The code"),
        title=_clean(title, "The title", 200),
        term=_term(term),
        credits=credits,
    )
    db.add(course)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict("This department already has a course with that code and term.") from exc
    await audit(db, actor, "course.create", resource_type="course", resource_id=course.id)
    await db.commit()
    return await _course_row(db, course)


async def update_course(
    db: AsyncSession,
    actor: Principal,
    course_id: uuid.UUID,
    *,
    title: str | None,
    credits: int | None,
) -> CourseRow:
    course = await _course(db, actor, course_id, "course.update")
    changed: list[str] = []
    if title is not None:
        course.title = _clean(title, "The title", 200)
        changed.append("title")
    if credits is not None:
        if not 0 <= credits <= 30:
            raise InvalidInput("Credits must be between 0 and 30.")
        course.credits = credits
        changed.append("credits")
    await audit(
        db,
        actor,
        "course.update",
        resource_type="course",
        resource_id=course.id,
        fields=",".join(changed),
    )
    await db.commit()
    return await _course_row(db, course)


async def delete_course(db: AsyncSession, actor: Principal, course_id: uuid.UUID) -> None:
    course = await _course(db, actor, course_id, "course.delete")
    if await count(
        db,
        select(func.count())
        .select_from(m.CourseEnrollment)
        .where(m.CourseEnrollment.course_id == course_id),
    ):
        raise Conflict("This course has enrolment history, so it cannot be deleted.")
    await db.execute(
        delete(m.GroupSnapshot).where(
            m.GroupSnapshot.institution_id == actor.institution_id,
            m.GroupSnapshot.group_kind == "class",
            m.GroupSnapshot.group_id == course_id,
        )
    )
    await db.delete(course)
    await audit(db, actor, "course.delete", resource_type="course", resource_id=course_id)
    await db.commit()


async def assign_teacher(
    db: AsyncSession, actor: Principal, course_id: uuid.UUID, teacher_id: uuid.UUID
) -> None:
    await _course(db, actor, course_id, "course.assign_teacher")
    teacher = await db.get(m.Teacher, teacher_id)
    if teacher is None or teacher.institution_id != actor.institution_id:
        raise NotFound
    exists = await db.scalar(
        select(m.CourseTeacher.course_id).where(
            m.CourseTeacher.course_id == course_id, m.CourseTeacher.teacher_id == teacher_id
        )
    )
    if exists is None:
        db.add(
            m.CourseTeacher(
                course_id=course_id, teacher_id=teacher_id, institution_id=actor.institution_id
            )
        )
    await audit(
        db,
        actor,
        "course.assign_teacher",
        resource_type="course",
        resource_id=course_id,
        teacher_id=str(teacher_id),
    )
    await db.commit()


async def unassign_teacher(
    db: AsyncSession, actor: Principal, course_id: uuid.UUID, teacher_id: uuid.UUID
) -> None:
    await _course(db, actor, course_id, "course.unassign_teacher")
    await db.execute(
        delete(m.CourseTeacher).where(
            m.CourseTeacher.course_id == course_id,
            m.CourseTeacher.teacher_id == teacher_id,
            m.CourseTeacher.institution_id == actor.institution_id,
        )
    )
    await audit(
        db,
        actor,
        "course.unassign_teacher",
        resource_type="course",
        resource_id=course_id,
        teacher_id=str(teacher_id),
    )
    await db.commit()


async def enrol(
    db: AsyncSession, actor: Principal, course_id: uuid.UUID, student_id: uuid.UUID
) -> None:
    await _course(db, actor, course_id, "course.enrol")
    student = await db.get(m.Student, student_id)
    if student is None or student.institution_id != actor.institution_id:
        raise NotFound
    row = await db.scalar(
        select(m.CourseEnrollment).where(
            m.CourseEnrollment.course_id == course_id, m.CourseEnrollment.student_id == student_id
        )
    )
    if row is None:
        db.add(
            m.CourseEnrollment(
                id=uuid7(),
                institution_id=actor.institution_id,
                course_id=course_id,
                student_id=student_id,
                status=EnrollmentStatus.ENROLLED,
            )
        )
    else:
        row.status = EnrollmentStatus.ENROLLED
    await cohort_stats.invalidate_for_student(db, actor.institution_id, student_id)
    await audit(
        db,
        actor,
        "course.enrol",
        resource_type="course",
        resource_id=course_id,
        subject_student_id=student_id,
    )
    await db.commit()


async def drop(
    db: AsyncSession, actor: Principal, course_id: uuid.UUID, student_id: uuid.UUID
) -> None:
    """Mark the enrolment dropped. The row stays, because referrals point at it."""
    await _course(db, actor, course_id, "course.drop")
    row = await db.scalar(
        select(m.CourseEnrollment).where(
            m.CourseEnrollment.course_id == course_id,
            m.CourseEnrollment.student_id == student_id,
            m.CourseEnrollment.institution_id == actor.institution_id,
        )
    )
    if row is None:
        raise NotFound
    row.status = EnrollmentStatus.DROPPED
    await cohort_stats.invalidate_for_student(db, actor.institution_id, student_id)
    await audit(
        db,
        actor,
        "course.drop",
        resource_type="course",
        resource_id=course_id,
        subject_student_id=student_id,
    )
    await db.commit()


# ---- people ----------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class StudentRow:
    student: m.Student
    user: m.User
    department: m.Department


@dataclasses.dataclass(frozen=True)
class StudentPage:
    items: list[StudentRow]
    total: int


@dataclasses.dataclass(frozen=True)
class StudentDetail:
    row: StudentRow
    courses: list[tuple[m.Course, EnrollmentStatus]]


def _people_filters(
    actor: Principal, status: UserStatus | None, query: str | None, number_column: object
) -> list[object]:
    where: list[object] = [
        m.User.institution_id == actor.institution_id,
        m.User.deleted_at.is_(None),
    ]
    if status is not None:
        where.append(m.User.status == status)
    if query and query.strip():
        pattern = like(query)
        where.append(
            or_(
                m.User.full_name.ilike(pattern, escape=LIKE_ESCAPE),
                m.User.email.ilike(pattern, escape=LIKE_ESCAPE),
                number_column.ilike(pattern, escape=LIKE_ESCAPE),  # type: ignore[attr-defined]
            )
        )
    return where


async def list_students(
    db: AsyncSession,
    actor: Principal,
    *,
    department_id: uuid.UUID | None,
    status: UserStatus | None,
    query: str | None,
    limit: int,
    offset: int,
) -> StudentPage:
    where = _people_filters(actor, status, query, m.Student.student_number)
    if department_id is not None:
        where.append(m.Student.department_id == department_id)
    base = (
        select(m.Student, m.User, m.Department)
        .join(m.User, m.User.id == m.Student.user_id)
        .join(
            m.Department,
            (m.Department.id == m.Student.department_id)
            & (m.Department.institution_id == m.Student.institution_id),
        )
        .where(*where)  # type: ignore[arg-type]
    )
    total = await count(db, select(func.count()).select_from(base.subquery()))
    rows = (
        await db.execute(
            base.order_by(m.User.full_name, m.User.id)
            .limit(min(limit, MAX_LIMIT))
            .offset(max(offset, 0))
        )
    ).all()
    return StudentPage([StudentRow(s, u, d) for s, u, d in rows], total)


async def _student(
    db: AsyncSession, actor: Principal, student_id: uuid.UUID, action: str
) -> StudentRow:
    row = (
        await db.execute(
            select(m.Student, m.User, m.Department)
            .join(m.User, m.User.id == m.Student.user_id)
            .join(
                m.Department,
                (m.Department.id == m.Student.department_id)
                & (m.Department.institution_id == m.Student.institution_id),
            )
            .where(m.Student.user_id == student_id, m.User.deleted_at.is_(None))
        )
    ).one_or_none()
    if row is None:
        raise NotFound
    student, user, dept = row
    enforce(
        can_administer(actor, institution_id=student.institution_id),
        action=action,
        resource_type="student",
        resource_id=student_id,
        subject_student_id=student_id,
    )
    return StudentRow(student, user, dept)


async def student_detail(
    db: AsyncSession, actor: Principal, student_id: uuid.UUID
) -> StudentDetail:
    row = await _student(db, actor, student_id, "student.read")
    courses = (
        await db.execute(
            select(m.Course, m.CourseEnrollment.status)
            .join(m.CourseEnrollment, m.CourseEnrollment.course_id == m.Course.id)
            .where(m.CourseEnrollment.student_id == student_id)
            .order_by(m.Course.term.desc(), m.Course.code)
        )
    ).all()
    return StudentDetail(row, [(c, s) for c, s in courses])


async def update_student(
    db: AsyncSession,
    actor: Principal,
    student_id: uuid.UUID,
    *,
    department_id: uuid.UUID | None,
    year_of_study: int | None,
    enrollment_year: int | None,
    student_number: str | None,
) -> StudentRow:
    row = await _student(db, actor, student_id, "student.update")
    s = row.student
    changed: list[str] = []
    if department_id is not None and department_id != s.department_id:
        await _department(db, actor, department_id, "student.update")
        # Forget the old department's stored figures now and the new one's after the move.
        await cohort_stats.invalidate_for_student(db, actor.institution_id, student_id)
        s.department_id = department_id
        changed.append("department")
    if year_of_study is not None:
        if not 1 <= year_of_study <= 8:
            raise InvalidInput("Year of study must be between 1 and 8.")
        s.year_of_study = year_of_study
        changed.append("year_of_study")
    if enrollment_year is not None:
        if not 1990 <= enrollment_year <= 2100:
            raise InvalidInput("Enrolment year is out of range.")
        s.enrollment_year = enrollment_year
        changed.append("enrollment_year")
    if student_number is not None:
        s.student_number = _clean(student_number, "The student number", 40)
        changed.append("student_number")
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict("Another student already has this number.") from exc
    if "department" in changed:
        await cohort_stats.invalidate_for_student(db, actor.institution_id, student_id)
    await audit(
        db,
        actor,
        "student.update",
        resource_type="student",
        resource_id=student_id,
        subject_student_id=student_id,
        fields=",".join(changed),
    )
    await db.commit()
    return await _student(db, actor, student_id, "student.read")


@dataclasses.dataclass(frozen=True)
class TeacherRow:
    teacher: m.Teacher
    user: m.User
    department: m.Department
    courses: int


@dataclasses.dataclass(frozen=True)
class TeacherPage:
    items: list[TeacherRow]
    total: int


async def list_teachers(
    db: AsyncSession,
    actor: Principal,
    *,
    department_id: uuid.UUID | None,
    status: UserStatus | None,
    query: str | None,
    limit: int,
    offset: int,
) -> TeacherPage:
    where = _people_filters(actor, status, query, m.Teacher.employee_number)
    if department_id is not None:
        where.append(m.Teacher.department_id == department_id)
    base = (
        select(m.Teacher, m.User, m.Department)
        .join(m.User, m.User.id == m.Teacher.user_id)
        .join(
            m.Department,
            (m.Department.id == m.Teacher.department_id)
            & (m.Department.institution_id == m.Teacher.institution_id),
        )
        .where(*where)  # type: ignore[arg-type]
    )
    total = await count(db, select(func.count()).select_from(base.subquery()))
    rows = (
        await db.execute(
            base.order_by(m.User.full_name, m.User.id)
            .limit(min(limit, MAX_LIMIT))
            .offset(max(offset, 0))
        )
    ).all()
    items = [
        TeacherRow(
            t,
            u,
            d,
            await count(
                db,
                select(func.count())
                .select_from(m.CourseTeacher)
                .where(m.CourseTeacher.teacher_id == t.user_id),
            ),
        )
        for t, u, d in rows
    ]
    return TeacherPage(items, total)


async def update_teacher(
    db: AsyncSession,
    actor: Principal,
    teacher_id: uuid.UUID,
    *,
    department_id: uuid.UUID | None,
    title: str | None,
    employee_number: str | None,
) -> TeacherRow:
    teacher = await db.get(m.Teacher, teacher_id)
    if teacher is None:
        raise NotFound
    enforce(
        can_administer(actor, institution_id=teacher.institution_id),
        action="teacher.update",
        resource_type="teacher",
        resource_id=teacher_id,
    )
    changed: list[str] = []
    if department_id is not None and department_id != teacher.department_id:
        await _department(db, actor, department_id, "teacher.update")
        teacher.department_id = department_id
        changed.append("department")
    if title is not None:
        teacher.title = " ".join(title.split())[:100] or None
        changed.append("title")
    if employee_number is not None:
        teacher.employee_number = _clean(employee_number, "The employee number", 40)
        changed.append("employee_number")
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict("Another teacher already has this number.") from exc
    await audit(
        db,
        actor,
        "teacher.update",
        resource_type="teacher",
        resource_id=teacher_id,
        fields=",".join(changed),
    )
    await db.commit()
    page = await list_teachers(
        db, actor, department_id=None, status=None, query=teacher.employee_number, limit=1, offset=0
    )
    return page.items[0]


@dataclasses.dataclass(frozen=True)
class TherapistRow:
    therapist: m.Therapist
    user: m.User
    caseload: int


@dataclasses.dataclass(frozen=True)
class TherapistPage:
    items: list[TherapistRow]
    total: int


async def list_therapists(
    db: AsyncSession,
    actor: Principal,
    *,
    status: UserStatus | None,
    query: str | None,
    limit: int,
    offset: int,
) -> TherapistPage:
    where = _people_filters(actor, status, query, m.Therapist.licence_number)
    base = (
        select(m.Therapist, m.User).join(m.User, m.User.id == m.Therapist.user_id).where(*where)  # type: ignore[arg-type]
    )
    total = await count(db, select(func.count()).select_from(base.subquery()))
    rows = (
        await db.execute(
            base.order_by(m.User.full_name, m.User.id)
            .limit(min(limit, MAX_LIMIT))
            .offset(max(offset, 0))
        )
    ).all()
    items: list[TherapistRow] = []
    for t, u in rows:
        # A head count only: who is on a caseload is clinical and stays with the therapist.
        caseload = await count(
            db,
            select(func.count())
            .select_from(m.CareTeamMember)
            .where(m.CareTeamMember.therapist_id == t.user_id, m.CareTeamMember.ends_at.is_(None)),
        )
        items.append(TherapistRow(t, u, caseload))
    return TherapistPage(items, total)


async def update_therapist(
    db: AsyncSession,
    actor: Principal,
    therapist_id: uuid.UUID,
    *,
    max_caseload: int | None,
    licence_number: str | None,
) -> TherapistRow:
    therapist = await db.get(m.Therapist, therapist_id)
    if therapist is None:
        raise NotFound
    enforce(
        can_administer(actor, institution_id=therapist.institution_id),
        action="therapist.update",
        resource_type="therapist",
        resource_id=therapist_id,
    )
    changed: list[str] = []
    if max_caseload is not None:
        if not 1 <= max_caseload <= 500:
            raise InvalidInput("Caseload limit must be between 1 and 500.")
        therapist.max_caseload = max_caseload
        changed.append("max_caseload")
    if licence_number is not None:
        # A different licence is a different person to verify: back to pending.
        number = _clean(licence_number, "The licence number", 60)
        if number != therapist.licence_number:
            therapist.licence_number = number
            therapist.verification_status = VerificationStatus.PENDING
            therapist.verified_at = None
            therapist.verified_by = None
            changed.append("licence_number")
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict("Another therapist already has this licence number.") from exc
    await audit(
        db,
        actor,
        "therapist.update",
        resource_type="therapist",
        resource_id=therapist_id,
        fields=",".join(changed),
    )
    await db.commit()
    page = await list_therapists(
        db, actor, status=None, query=therapist.licence_number, limit=1, offset=0
    )
    return page.items[0]
