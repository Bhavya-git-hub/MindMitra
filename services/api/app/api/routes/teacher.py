"""The teacher portal: dashboard, classes, anonymous group figures, referrals, resources.

Every route needs a teacher permission, which students, therapists and administrators do not
hold, so they are refused before anything is read. Each use case then checks that the class,
department, referral or request really belongs to this teacher. No route here returns an
individual student's wellbeing data; see ``schemas/teacher.py`` for what each response carries.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.api.schemas import student as ss
from app.api.schemas import teacher as s
from app.application import directory, referrals, teacher_portal, teacher_support
from app.domain.auth.permissions import Permission
from app.domain.auth.policies import Principal
from app.domain.wellness import cohort_report
from app.infrastructure.db.enums import ReferralStatus, ResourceType, TeacherSupportStatus

router = APIRouter(prefix="/teacher", tags=["teacher"])
Db = Annotated[AsyncSession, Depends(get_db)]


def _guard(permission: Permission) -> Any:
    return Depends(require_permission(permission))


Insights = Annotated[Principal, _guard(Permission.CLASS_INSIGHTS_READ)]
Referrals = Annotated[Principal, _guard(Permission.REFERRAL_MANAGE_OWN)]
Requests = Annotated[Principal, _guard(Permission.TEACHER_SUPPORT_MANAGE)]
Faculty = Annotated[Principal, _guard(Permission.FACULTY_RESOURCE_READ)]
Weeks = Annotated[int | None, Query(description="4, 8 or 12 calendar weeks")]


@router.get("/dashboard")
async def dashboard(db: Db, principal: Insights) -> s.DashboardOut:
    return s.dashboard_out(await teacher_portal.dashboard(db, principal))


# ---- classes and group figures --------------------------------------------------------------


@router.get("/classes")
async def classes(db: Db, principal: Insights) -> list[s.ClassOut]:
    return [s.class_out(c) for c in await teacher_portal.list_classes(db, principal)]


@router.get("/classes/{course_id}")
async def get_class(course_id: uuid.UUID, db: Db, principal: Insights) -> s.ClassOut:
    return s.class_out(await teacher_portal.get_class(db, principal, course_id))


@router.get("/classes/{course_id}/students")
async def class_roster(course_id: uuid.UUID, db: Db, principal: Referrals) -> list[s.RosterOut]:
    """Names only, so a teacher can choose who a referral is about."""
    rows = await teacher_portal.roster(db, principal, course_id)
    return [s.RosterOut(student_id=r.student_id, name=r.name) for r in rows]


@router.get("/classes/{course_id}/analytics")
async def class_analytics(
    course_id: uuid.UUID, db: Db, principal: Insights, weeks: Weeks = None
) -> s.ClassAnalyticsOut:
    info, view = await teacher_portal.class_view(db, principal, course_id, weeks)
    return s.ClassAnalyticsOut(group=s.class_out(info), analytics=s.analytics_out(view))


@router.get("/classes/{course_id}/report")
async def class_report(
    course_id: uuid.UUID, db: Db, principal: Insights, weeks: Weeks = None
) -> s.ReportOut:
    _, view = await teacher_portal.class_view(db, principal, course_id, weeks)
    return s.report_out(view)


@router.get("/classes/{course_id}/report.csv")
async def class_report_csv(
    course_id: uuid.UUID, db: Db, principal: Insights, weeks: Weeks = None
) -> Response:
    _, view = await teacher_portal.class_view(db, principal, course_id, weeks)
    return _csv(view)


@router.get("/departments/{department_id}/analytics")
async def department_analytics(
    department_id: uuid.UUID, db: Db, principal: Insights, weeks: Weeks = None
) -> s.DepartmentAnalyticsOut:
    dept, view = await teacher_portal.department_view(db, principal, department_id, weeks)
    return s.DepartmentAnalyticsOut(department_id=dept.id, analytics=s.analytics_out(view))


@router.get("/departments/{department_id}/report")
async def department_report(
    department_id: uuid.UUID, db: Db, principal: Insights, weeks: Weeks = None
) -> s.ReportOut:
    _, view = await teacher_portal.department_view(db, principal, department_id, weeks)
    return s.report_out(view)


@router.get("/departments/{department_id}/report.csv")
async def department_report_csv(
    department_id: uuid.UUID, db: Db, principal: Insights, weeks: Weeks = None
) -> Response:
    _, view = await teacher_portal.department_view(db, principal, department_id, weeks)
    return _csv(view)


def _csv(view: teacher_portal.GroupView) -> Response:
    return Response(
        cohort_report.to_csv(view.figures.analytics),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="anonymous-wellbeing-report.csv"'},
    )


# ---- referrals ------------------------------------------------------------------------------


@router.post("/referrals", status_code=201)
async def create_referral(body: s.ReferralIn, db: Db, principal: Referrals) -> s.ReferralDetailOut:
    view = await referrals.create(
        db,
        principal,
        student_id=body.student_id,
        course_id=body.course_id,
        category=body.category,
        urgency=body.urgency,
        note=body.note,
    )
    return s.referral_detail_out(view)


@router.get("/referrals")
async def list_referrals(
    db: Db, principal: Referrals, status: ReferralStatus | None = None
) -> list[s.ReferralOut]:
    return [s.referral_out(v) for v in await referrals.list_mine(db, principal, status)]


@router.get("/referrals/{referral_id}")
async def get_referral(referral_id: uuid.UUID, db: Db, principal: Referrals) -> s.ReferralDetailOut:
    return s.referral_detail_out(await referrals.get_mine(db, principal, referral_id))


# ---- requests students have sent this teacher -----------------------------------------------


@router.get("/support-requests")
async def list_support_requests(
    db: Db, principal: Requests, status: TeacherSupportStatus | None = None
) -> list[s.SupportRequestOut]:
    rows = await teacher_support.list_for_teacher(db, principal, status)
    return [s.support_request_out(v) for v in rows]


@router.post("/support-requests/{request_id}/acknowledge")
async def acknowledge_support_request(
    request_id: uuid.UUID, db: Db, principal: Requests
) -> s.SupportRequestOut:
    return s.support_request_out(await teacher_support.acknowledge(db, principal, request_id))


@router.post("/support-requests/{request_id}/close")
async def close_support_request(
    request_id: uuid.UUID, db: Db, principal: Requests
) -> s.SupportRequestOut:
    return s.support_request_out(await teacher_support.close(db, principal, request_id))


# ---- faculty resources ----------------------------------------------------------------------


@router.get("/resources")
async def list_resources(
    db: Db,
    principal: Faculty,
    resource_type: ResourceType | None = None,
    tag: str | None = None,
    q: Annotated[str | None, Query(max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ss.ResourceOut]:
    rows = await directory.list_resources(
        db,
        principal,
        resource_type=resource_type,
        tag=tag,
        query=q,
        limit=limit,
        faculty=True,
    )
    return [ss.resource_out(r) for r in rows]


@router.get("/resources/{resource_id}")
async def get_resource(resource_id: uuid.UUID, db: Db, principal: Faculty) -> ss.ResourceDetailOut:
    return ss.resource_detail_out(
        await directory.get_resource(db, principal, resource_id, faculty=True)
    )
