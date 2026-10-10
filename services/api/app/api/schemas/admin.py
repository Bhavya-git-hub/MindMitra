"""Request and response bodies for the administrator API (snake_case, ISO 8601 UTC).

Responses carry account, structure and configuration data. None of them carries a wellbeing
score, journal text, message, therapy note, appointment reason, referral note, AI conversation
or the identity of anyone in a care relationship. Group figures reuse the teacher portal's
``AnalyticsOut``, which is built only from the privacy rules in ``domain.wellness.cohort``.
"""

import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.api.schemas import teacher as ts
from app.application import (
    admin,
    admin_audit,
    admin_directory,
    admin_insights,
    institution_settings,
)
from app.application.therapist_access import effective_verification
from app.domain import settings as domain_settings
from app.infrastructure.db import models as m

Req20 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
Req40 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
Req60 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
Req200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Req500 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Opt40 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)]
Opt80 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)]
Opt100 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]
Opt300 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
Opt500 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Tag = Annotated[str, StringConstraints(max_length=40)]
Window = Annotated[int | None, Field(description="4, 8 or 12 completed calendar weeks")]


class Page[T](BaseModel):
    items: list[T]
    total: int


# ---- users ------------------------------------------------------------------------------------


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    status: str
    created_at: dt.datetime
    last_login_at: dt.datetime | None


def user_out(u: m.User) -> UserOut:
    return UserOut(
        id=u.id,
        email=u.email,
        full_name=u.full_name,
        role=u.role.value,
        status=u.status.value,
        created_at=u.created_at,
        last_login_at=u.last_login_at,
    )


def user_page(p: admin.UserPage) -> Page[UserOut]:
    return Page(items=[user_out(u) for u in p.items], total=p.total)


# ---- departments and courses ----------------------------------------------------------------


class DepartmentOut(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    students: int
    teachers: int
    courses: int


class DepartmentIn(BaseModel):
    name: Req200
    code: Req20


class DepartmentPatchIn(BaseModel):
    name: Req200 | None = None
    code: Req20 | None = None


def department_out(r: admin_directory.DepartmentRow) -> DepartmentOut:
    d = r.department
    return DepartmentOut(
        id=d.id,
        name=d.name,
        code=d.code,
        students=r.students,
        teachers=r.teachers,
        courses=r.courses,
    )


class CourseOut(BaseModel):
    id: uuid.UUID
    department_id: uuid.UUID
    department_name: str
    code: str
    title: str
    term: str
    credits: int
    teachers: int
    enrolled: int


class CourseIn(BaseModel):
    department_id: uuid.UUID
    code: Req20
    title: Req200
    term: Req20
    credits: int = Field(default=3, ge=0, le=30)


class CoursePatchIn(BaseModel):
    title: Req200 | None = None
    credits: int | None = Field(default=None, ge=0, le=30)


class PersonOut(BaseModel):
    id: uuid.UUID
    full_name: str
    number: str


class CourseDetailOut(BaseModel):
    course: CourseOut
    teachers: list[PersonOut]
    students: list[PersonOut]


def course_out(r: admin_directory.CourseRow) -> CourseOut:
    c = r.course
    return CourseOut(
        id=c.id,
        department_id=c.department_id,
        department_name=r.department.name,
        code=c.code,
        title=c.title,
        term=c.term,
        credits=c.credits,
        teachers=r.teachers,
        enrolled=r.enrolled,
    )


def course_detail_out(d: admin_directory.CourseDetail) -> CourseDetailOut:
    return CourseDetailOut(
        course=course_out(d.row),
        teachers=[
            PersonOut(id=p.user_id, full_name=p.full_name, number=p.number) for p in d.teachers
        ],
        students=[
            PersonOut(id=p.user_id, full_name=p.full_name, number=p.number) for p in d.students
        ],
    )


# ---- students, teachers, therapists ---------------------------------------------------------


class StudentOut(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    status: str
    student_number: str
    department_id: uuid.UUID
    department_name: str
    enrollment_year: int
    year_of_study: int


class StudentCourseOut(BaseModel):
    course_id: uuid.UUID
    code: str
    title: str
    term: str
    status: str


class StudentDetailOut(BaseModel):
    student: StudentOut
    courses: list[StudentCourseOut]


class StudentPatchIn(BaseModel):
    department_id: uuid.UUID | None = None
    year_of_study: int | None = Field(default=None, ge=1, le=8)
    enrollment_year: int | None = Field(default=None, ge=1990, le=2100)
    student_number: Req40 | None = None


def student_out(r: admin_directory.StudentRow) -> StudentOut:
    return StudentOut(
        id=r.student.user_id,
        full_name=r.user.full_name,
        email=r.user.email,
        status=r.user.status.value,
        student_number=r.student.student_number,
        department_id=r.department.id,
        department_name=r.department.name,
        enrollment_year=r.student.enrollment_year,
        year_of_study=r.student.year_of_study,
    )


def student_detail_out(d: admin_directory.StudentDetail) -> StudentDetailOut:
    return StudentDetailOut(
        student=student_out(d.row),
        courses=[
            StudentCourseOut(
                course_id=c.id, code=c.code, title=c.title, term=c.term, status=status.value
            )
            for c, status in d.courses
        ],
    )


class TeacherAccountOut(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    status: str
    employee_number: str
    title: str | None
    department_id: uuid.UUID
    department_name: str
    courses: int


class TeacherPatchIn(BaseModel):
    department_id: uuid.UUID | None = None
    title: Opt100 | None = None
    employee_number: Req40 | None = None


def teacher_account_out(r: admin_directory.TeacherRow) -> TeacherAccountOut:
    return TeacherAccountOut(
        id=r.teacher.user_id,
        full_name=r.user.full_name,
        email=r.user.email,
        status=r.user.status.value,
        employee_number=r.teacher.employee_number,
        title=r.teacher.title,
        department_id=r.department.id,
        department_name=r.department.name,
        courses=r.courses,
    )


class TherapistAccountOut(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    status: str
    licence_number: str
    verification_status: str
    accepting_new_students: bool
    max_caseload: int
    caseload: int


class TherapistPatchIn(BaseModel):
    max_caseload: int | None = Field(default=None, ge=1, le=500)
    licence_number: Req60 | None = None


def therapist_account_out(r: admin_directory.TherapistRow) -> TherapistAccountOut:
    t = r.therapist
    return TherapistAccountOut(
        id=t.user_id,
        full_name=r.user.full_name,
        email=r.user.email,
        status=r.user.status.value,
        licence_number=t.licence_number,
        verification_status=effective_verification(t),
        accepting_new_students=t.accepting_new_students,
        max_caseload=t.max_caseload,
        caseload=r.caseload,
    )


# ---- resources ------------------------------------------------------------------------------


class ResourceOut(BaseModel):
    id: uuid.UUID
    title: str
    summary: str
    body: str | None
    url: str | None
    resource_type: str
    tags: list[str]
    language: str
    duration_minutes: int | None
    is_published: bool
    source: Literal["global", "institution"]
    audience: Literal["students", "faculty"]
    editable: bool
    reviewed_at: dt.datetime | None


class ResourceIn(BaseModel):
    title: Req200
    summary: Req500
    resource_type: Literal["article", "video", "exercise", "audio", "service"]
    body: Annotated[str, StringConstraints(max_length=20000)] | None = None
    url: Annotated[str, StringConstraints(max_length=500)] | None = None
    tags: list[Annotated[str, StringConstraints(max_length=40)]] = Field(
        default_factory=list, max_length=10
    )
    language: Annotated[str, StringConstraints(max_length=12)] = "en"
    duration_minutes: int | None = Field(default=None, ge=1, le=600)
    publish: bool = False


class PublishIn(BaseModel):
    published: bool


def resource_out(r: m.Resource) -> ResourceOut:
    return ResourceOut(
        id=r.id,
        title=r.title,
        summary=r.summary,
        body=r.body,
        url=r.url,
        resource_type=r.resource_type.value,
        tags=list(r.tags),
        language=r.language,
        duration_minutes=r.duration_minutes,
        is_published=r.is_published,
        source="global" if r.institution_id is None else "institution",
        audience="faculty" if "faculty" in r.tags else "students",
        editable=r.institution_id is not None,
        reviewed_at=r.reviewed_at,
    )


# ---- dashboard, analytics, oversight --------------------------------------------------------


class AccountCountsOut(BaseModel):
    role: str
    active: int
    invited: int
    suspended: int


class DashboardOut(BaseModel):
    accounts: list[AccountCountsOut]
    pending_verifications: int
    licences_expiring: int
    draft_resources: int
    alerts_awaiting: int
    alerts_overdue: int
    denied_last_7_days: int
    generated_at: dt.datetime


class WeekCountOut(BaseModel):
    week_start: dt.date
    count: int | None = Field(description="null means fewer than 5")


def _accounts(rows: list[admin_insights.AccountCounts]) -> list[AccountCountsOut]:
    return [
        AccountCountsOut(
            role=a.role.value, active=a.active, invited=a.invited, suspended=a.suspended
        )
        for a in rows
    ]


def _weeks(rows: list[admin_insights.WeekCount]) -> list[WeekCountOut]:
    return [WeekCountOut(week_start=w.week_start, count=w.count) for w in rows]


def dashboard_out(d: admin_insights.Dashboard) -> DashboardOut:
    return DashboardOut(
        accounts=_accounts(d.accounts),
        pending_verifications=d.pending_verifications,
        licences_expiring=d.licences_expiring,
        draft_resources=d.draft_resources,
        alerts_awaiting=d.alerts_awaiting,
        alerts_overdue=d.alerts_overdue,
        denied_last_7_days=d.denied_last_7_days,
        generated_at=d.generated_at,
    )


class PlatformAnalyticsOut(BaseModel):
    window_weeks: int
    accounts: list[AccountCountsOut]
    wellbeing: ts.AnalyticsOut
    appointments_booked: list[WeekCountOut]
    alerts_raised: list[WeekCountOut]
    resources_published: dict[str, int]
    small_number_note: str
    generated_at: dt.datetime


def analytics_out(a: admin_insights.PlatformAnalytics) -> PlatformAnalyticsOut:
    return PlatformAnalyticsOut(
        window_weeks=a.weeks,
        accounts=_accounts(a.accounts),
        wellbeing=ts.analytics_out(a.wellbeing),
        appointments_booked=_weeks(a.appointments_booked),
        alerts_raised=_weeks(a.alerts_raised),
        resources_published={k.value: v for k, v in a.resources_published.items()},
        small_number_note=(
            f"Weekly counts of 1 to {admin_insights.SMALL_COUNT - 1} are shown as "
            f"“fewer than {admin_insights.SMALL_COUNT}” so a quiet week cannot point at a person."
        ),
        generated_at=a.generated_at,
    )


class StatusCountOut(BaseModel):
    status: str
    count: int | None


class TherapistLoadOut(BaseModel):
    therapist_id: uuid.UUID
    full_name: str
    upcoming: int
    completed: int
    no_shows: int
    cancelled: int


class OversightOut(BaseModel):
    window_weeks: int
    by_status: list[StatusCountOut]
    weekly_scheduled: list[WeekCountOut]
    confirmed_next_7_days: int | None
    stale_requests: int
    therapists: list[TherapistLoadOut]
    note: str
    generated_at: dt.datetime


def oversight_out(o: admin_insights.Oversight) -> OversightOut:
    return OversightOut(
        window_weeks=o.weeks,
        by_status=[StatusCountOut(status=s.status.value, count=s.count) for s in o.by_status],
        weekly_scheduled=_weeks(o.weekly_scheduled),
        confirmed_next_7_days=o.upcoming_week,
        stale_requests=o.stale_requests,
        therapists=[
            TherapistLoadOut(
                therapist_id=t.therapist_id,
                full_name=t.full_name,
                upcoming=t.upcoming,
                completed=t.completed,
                no_shows=t.no_shows,
                cancelled=t.cancelled,
            )
            for t in o.therapists
        ],
        note=(
            "Counts only. Who attended, why, and what was discussed stay with the student and "
            "their therapist."
        ),
        generated_at=o.generated_at,
    )


# ---- audit ------------------------------------------------------------------------------------


class AuditEventOut(BaseModel):
    seq: int
    occurred_at: dt.datetime
    actor_id: uuid.UUID | None
    actor_role: str | None
    action: str
    outcome: str
    resource_type: str | None
    resource_id: uuid.UUID | None
    subject_student_id: uuid.UUID | None
    reason: str | None
    details: dict[str, Any]


def audit_event_out(r: m.AuditLog) -> AuditEventOut:
    return AuditEventOut(
        seq=r.seq,
        occurred_at=r.occurred_at,
        actor_id=r.actor_id,
        actor_role=r.actor_role.value if r.actor_role else None,
        action=r.action,
        outcome=r.outcome.value,
        resource_type=r.resource_type,
        resource_id=r.resource_id,
        subject_student_id=r.subject_student_id,
        reason=r.reason,
        details=r.details,
    )


class ChainStatusOut(BaseModel):
    intact: bool
    first_bad_seq: int | None
    events: int
    checked_at: dt.datetime


def chain_out(c: admin_audit.ChainStatus) -> ChainStatusOut:
    return ChainStatusOut(
        intact=c.intact, first_bad_seq=c.first_bad_seq, events=c.events, checked_at=c.checked_at
    )


# ---- settings ---------------------------------------------------------------------------------


class NotificationSettingsOut(BaseModel):
    values: domain_settings.NotificationSettings
    fixed_rules: list[str]


class SafetySettingsOut(BaseModel):
    values: domain_settings.SafetySettings
    fixed_rules: list[str]


class NotificationSettingsPatchIn(BaseModel):
    reminders_enabled: bool | None = None
    appointment_reminder_hours: list[int] | None = None
    recommendation_notifications: bool | None = None
    goal_reminders: bool | None = None
    email_enabled: bool | None = None


class SafetySettingsPatchIn(BaseModel):
    alert_ack_minutes: int | None = None


class SettingsOut(BaseModel):
    notifications: NotificationSettingsOut
    safety: SafetySettingsOut


def settings_out(s: institution_settings.Settings) -> SettingsOut:
    return SettingsOut(
        notifications=NotificationSettingsOut(
            values=s.notifications, fixed_rules=list(domain_settings.NOTIFICATION_INVARIANTS)
        ),
        safety=SafetySettingsOut(
            values=s.safety, fixed_rules=list(domain_settings.SAFETY_INVARIANTS)
        ),
    )


class CrisisContactOut(BaseModel):
    id: uuid.UUID
    label: str
    kind: str
    phone: str | None
    url: str | None
    description: str | None
    hours: str | None
    sort_order: int
    is_active: bool
    editable: bool


class CrisisContactIn(BaseModel):
    label: Req200
    kind: Literal["emergency", "helpline", "campus"]
    phone: Opt40 | None = None
    url: Opt500 | None = None
    description: Opt300 | None = None
    hours: Opt80 | None = None
    sort_order: int = Field(default=100, ge=0, le=1000)
    is_active: bool = True


class CrisisContactPatchIn(BaseModel):
    label: Req200 | None = None
    phone: Opt40 | None = None
    url: Opt500 | None = None
    description: Opt300 | None = None
    hours: Opt80 | None = None
    sort_order: int | None = Field(default=None, ge=0, le=1000)
    is_active: bool | None = None


def contact_out(c: m.CrisisContact) -> CrisisContactOut:
    return CrisisContactOut(
        id=c.id,
        label=c.label,
        kind=c.kind.value,
        phone=c.phone,
        url=c.url,
        description=c.description,
        hours=c.hours,
        sort_order=c.sort_order,
        is_active=c.is_active,
        editable=c.institution_id is not None,
    )
