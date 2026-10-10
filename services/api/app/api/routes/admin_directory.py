"""Administrator endpoints for people records and the academic structure.

Students, teachers and therapists (registrar-style details), departments, courses, who teaches
a course and who is enrolled. Nothing here returns wellbeing, conversation, therapy or alert data.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.api.schemas import admin as s
from app.application import admin_directory as d
from app.domain.auth.permissions import Permission
from app.domain.auth.policies import Principal
from app.infrastructure.db.enums import UserStatus

router = APIRouter(prefix="/admin", tags=["admin"])
Db = Annotated[AsyncSession, Depends(get_db)]


def _guard(permission: Permission) -> Any:
    return Depends(require_permission(permission))


Students = Annotated[Principal, _guard(Permission.STUDENT_RECORD_MANAGE)]
Teachers = Annotated[Principal, _guard(Permission.TEACHER_RECORD_MANAGE)]
Therapists = Annotated[Principal, _guard(Permission.THERAPIST_RECORD_MANAGE)]
Departments = Annotated[Principal, _guard(Permission.DEPARTMENT_MANAGE)]
Courses = Annotated[Principal, _guard(Permission.COURSE_MANAGE)]
Search = Annotated[str | None, Query(max_length=80)]
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0, le=100_000)]
NoContent = status.HTTP_204_NO_CONTENT


# ---- departments -----------------------------------------------------------------------------


@router.get("/departments")
async def list_departments(db: Db, principal: Departments) -> list[s.DepartmentOut]:
    return [s.department_out(r) for r in await d.list_departments(db, principal)]


@router.post("/departments", status_code=status.HTTP_201_CREATED)
async def create_department(
    body: s.DepartmentIn, db: Db, principal: Departments
) -> s.DepartmentOut:
    dept = await d.create_department(db, principal, name=body.name, code=body.code)
    return s.department_out(d.DepartmentRow(dept, 0, 0, 0))


@router.patch("/departments/{department_id}")
async def update_department(
    department_id: uuid.UUID, body: s.DepartmentPatchIn, db: Db, principal: Departments
) -> s.DepartmentOut:
    await d.update_department(db, principal, department_id, name=body.name, code=body.code)
    rows = await d.list_departments(db, principal)
    return s.department_out(next(r for r in rows if r.department.id == department_id))


@router.delete("/departments/{department_id}", status_code=NoContent)
async def delete_department(department_id: uuid.UUID, db: Db, principal: Departments) -> Response:
    await d.delete_department(db, principal, department_id)
    return Response(status_code=NoContent)


# ---- courses ---------------------------------------------------------------------------------


@router.get("/courses")
async def list_courses(
    db: Db,
    principal: Courses,
    department_id: uuid.UUID | None = None,
    term: Annotated[str | None, Query(max_length=20)] = None,
    q: Search = None,
) -> list[s.CourseOut]:
    rows = await d.list_courses(db, principal, department_id=department_id, term=term, query=q)
    return [s.course_out(r) for r in rows]


@router.post("/courses", status_code=status.HTTP_201_CREATED)
async def create_course(body: s.CourseIn, db: Db, principal: Courses) -> s.CourseOut:
    row = await d.create_course(
        db,
        principal,
        department_id=body.department_id,
        code=body.code,
        title=body.title,
        term=body.term,
        credits=body.credits,
    )
    return s.course_out(row)


@router.get("/courses/{course_id}")
async def get_course(course_id: uuid.UUID, db: Db, principal: Courses) -> s.CourseDetailOut:
    return s.course_detail_out(await d.course_detail(db, principal, course_id))


@router.patch("/courses/{course_id}")
async def update_course(
    course_id: uuid.UUID, body: s.CoursePatchIn, db: Db, principal: Courses
) -> s.CourseOut:
    row = await d.update_course(db, principal, course_id, title=body.title, credits=body.credits)
    return s.course_out(row)


@router.delete("/courses/{course_id}", status_code=NoContent)
async def delete_course(course_id: uuid.UUID, db: Db, principal: Courses) -> Response:
    await d.delete_course(db, principal, course_id)
    return Response(status_code=NoContent)


@router.put("/courses/{course_id}/teachers/{teacher_id}", status_code=NoContent)
async def assign_teacher(
    course_id: uuid.UUID, teacher_id: uuid.UUID, db: Db, principal: Courses
) -> Response:
    await d.assign_teacher(db, principal, course_id, teacher_id)
    return Response(status_code=NoContent)


@router.delete("/courses/{course_id}/teachers/{teacher_id}", status_code=NoContent)
async def unassign_teacher(
    course_id: uuid.UUID, teacher_id: uuid.UUID, db: Db, principal: Courses
) -> Response:
    await d.unassign_teacher(db, principal, course_id, teacher_id)
    return Response(status_code=NoContent)


@router.put("/courses/{course_id}/students/{student_id}", status_code=NoContent)
async def enrol_student(
    course_id: uuid.UUID, student_id: uuid.UUID, db: Db, principal: Courses
) -> Response:
    await d.enrol(db, principal, course_id, student_id)
    return Response(status_code=NoContent)


@router.delete("/courses/{course_id}/students/{student_id}", status_code=NoContent)
async def drop_student(
    course_id: uuid.UUID, student_id: uuid.UUID, db: Db, principal: Courses
) -> Response:
    await d.drop(db, principal, course_id, student_id)
    return Response(status_code=NoContent)


# ---- students --------------------------------------------------------------------------------


@router.get("/students")
async def list_students(
    db: Db,
    principal: Students,
    department_id: uuid.UUID | None = None,
    user_status: Annotated[UserStatus | None, Query(alias="status")] = None,
    q: Search = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> s.Page[s.StudentOut]:
    page = await d.list_students(
        db,
        principal,
        department_id=department_id,
        status=user_status,
        query=q,
        limit=limit,
        offset=offset,
    )
    return s.Page(items=[s.student_out(r) for r in page.items], total=page.total)


@router.get("/students/{student_id}")
async def get_student(student_id: uuid.UUID, db: Db, principal: Students) -> s.StudentDetailOut:
    return s.student_detail_out(await d.student_detail(db, principal, student_id))


@router.patch("/students/{student_id}")
async def update_student(
    student_id: uuid.UUID, body: s.StudentPatchIn, db: Db, principal: Students
) -> s.StudentOut:
    row = await d.update_student(
        db,
        principal,
        student_id,
        department_id=body.department_id,
        year_of_study=body.year_of_study,
        enrollment_year=body.enrollment_year,
        student_number=body.student_number,
    )
    return s.student_out(row)


# ---- teachers --------------------------------------------------------------------------------


@router.get("/teachers")
async def list_teachers(
    db: Db,
    principal: Teachers,
    department_id: uuid.UUID | None = None,
    user_status: Annotated[UserStatus | None, Query(alias="status")] = None,
    q: Search = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> s.Page[s.TeacherAccountOut]:
    page = await d.list_teachers(
        db,
        principal,
        department_id=department_id,
        status=user_status,
        query=q,
        limit=limit,
        offset=offset,
    )
    return s.Page(items=[s.teacher_account_out(r) for r in page.items], total=page.total)


@router.patch("/teachers/{teacher_id}")
async def update_teacher(
    teacher_id: uuid.UUID, body: s.TeacherPatchIn, db: Db, principal: Teachers
) -> s.TeacherAccountOut:
    row = await d.update_teacher(
        db,
        principal,
        teacher_id,
        department_id=body.department_id,
        title=body.title,
        employee_number=body.employee_number,
    )
    return s.teacher_account_out(row)


# ---- therapist accounts ----------------------------------------------------------------------


@router.get("/therapist-accounts")
async def list_therapist_accounts(
    db: Db,
    principal: Therapists,
    user_status: Annotated[UserStatus | None, Query(alias="status")] = None,
    q: Search = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> s.Page[s.TherapistAccountOut]:
    page = await d.list_therapists(
        db, principal, status=user_status, query=q, limit=limit, offset=offset
    )
    return s.Page(items=[s.therapist_account_out(r) for r in page.items], total=page.total)


@router.patch("/therapist-accounts/{therapist_id}")
async def update_therapist_account(
    therapist_id: uuid.UUID, body: s.TherapistPatchIn, db: Db, principal: Therapists
) -> s.TherapistAccountOut:
    row = await d.update_therapist(
        db,
        principal,
        therapist_id,
        max_caseload=body.max_caseload,
        licence_number=body.licence_number,
    )
    return s.therapist_account_out(row)
