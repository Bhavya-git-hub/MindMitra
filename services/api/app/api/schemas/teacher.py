"""Request and response bodies for the teacher portal API (snake_case, ISO 8601 UTC).

Group figures are built only from ``domain.wellness.cohort`` output. Student identity appears in
exactly three places, each a deliberate act: the class roster (names), referrals the teacher
raised, and support requests a student chose to send. No response here carries a mood score,
journal text, assessment result, message, therapy note, diagnosis or AI conversation for a person.
"""

import datetime as dt
import uuid
from typing import Annotated

from pydantic import BaseModel, StringConstraints

from app.application import cohort_stats, referrals, teacher_portal, teacher_support
from app.domain.wellness import cohort, cohort_report
from app.infrastructure.db.enums import (
    ReferralCategory,
    ReferralOutcome,
    ReferralUrgency,
    TeacherSupportTopic,
)

Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=referrals.MAX_NOTE)]
Message = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=teacher_support.MAX_MESSAGE)
]

GROUP_DISCLAIMER = (
    "These figures come only from students who chose to share anonymous summaries. They describe "
    "a group, not any person, and they are not a diagnosis or a clinical assessment. Figures for "
    f"fewer than {cohort.MIN_COHORT} students are never shown."
)
STRAIN_EXPLAINER = (
    "Signs of strain means two or more of low energy, high stress and short sleep showing "
    "together over two weeks. It is a pattern in self-reports, not a diagnosis of burnout."
)

CATEGORY_LABELS = {
    ReferralCategory.ACADEMIC_DISTRESS: "Struggling with coursework",
    ReferralCategory.BEHAVIOUR_CHANGE: "A change in how they seem",
    ReferralCategory.WELLBEING_CONCERN: "A general wellbeing concern",
    ReferralCategory.SAFETY_CONCERN: "A possible safety concern",
}
URGENCY_LABELS = {
    ReferralUrgency.ROUTINE: "Routine",
    ReferralUrgency.SOON: "Soon",
    ReferralUrgency.URGENT: "Urgent",
}
TOPIC_LABELS = {
    TeacherSupportTopic.ACADEMIC_SUPPORT: "Help with the coursework",
    TeacherSupportTopic.WORKLOAD: "The workload feels heavy",
    TeacherSupportTopic.EXTENSION: "Asking for more time",
    TeacherSupportTopic.WELLBEING_CHAT: "A chat about how I am doing",
    TeacherSupportTopic.OTHER: "Something else",
}
OUTCOME_LABELS = {
    ReferralOutcome.CONTACTED_STUDENT: "Reached out to the student",
    ReferralOutcome.STUDENT_DECLINED: "Student chose not to take it further",
    ReferralOutcome.ALREADY_SUPPORTED: "Student already has support",
    ReferralOutcome.REFERRED_ELSEWHERE: "Pointed to another service",
    ReferralOutcome.NO_ACTION_NEEDED: "No action needed",
}
STATUS_LABELS = {
    "open": "Waiting",
    "acknowledged": "Seen",
    "closed": "Closed",
    "withdrawn": "Withdrawn by the student",
}


# ---- people and classes ---------------------------------------------------------------------


class TeacherOut(BaseModel):
    id: uuid.UUID
    name: str
    title: str | None
    department_id: uuid.UUID
    department_name: str


class ClassOut(BaseModel):
    id: uuid.UUID
    code: str
    title: str
    term: str
    department_name: str
    enrolled: int


class RosterOut(BaseModel):
    student_id: uuid.UUID
    name: str


def teacher_out(c: teacher_portal.TeacherContext) -> TeacherOut:
    return TeacherOut(
        id=c.teacher.user_id,
        name=c.name,
        title=c.teacher.title,
        department_id=c.department.id,
        department_name=c.department.name,
    )


def class_out(c: teacher_portal.ClassInfo) -> ClassOut:
    return ClassOut(
        id=c.course.id,
        code=c.course.code,
        title=c.course.title,
        term=c.course.term,
        department_name=c.department_name,
        enrolled=c.enrolled,
    )


# ---- group figures --------------------------------------------------------------------------


class ShareOut(BaseModel):
    """``shown``: ``percent`` (rounded to 5). ``few``/``most``/``hidden``: no number at all."""

    state: str
    percent: int | None
    text: str


class WeekOut(BaseModel):
    week_start: dt.date
    students_reporting: str | None
    mood: float | None
    energy: float | None
    stress: float | None
    sleep_hours: float | None
    sleep_quality: float | None
    check_in: ShareOut
    academic_stress: ShareOut
    strain: ShareOut


class StressorOut(BaseModel):
    key: str
    share: ShareOut


class BandOut(BaseModel):
    key: str
    label: str
    share: ShareOut


class ActionOut(BaseModel):
    key: str
    title: str
    message: str


class AnalyticsOut(BaseModel):
    label: str
    scope: str
    window_weeks: int
    state: str
    students_contributing: str | None
    min_group_size: int
    weeks: list[WeekOut]
    stressors: list[StressorOut]
    wellbeing: list[BandOut]
    actions: list[ActionOut]
    headline: list[str]
    generated_at: dt.datetime
    disclaimer: str = GROUP_DISCLAIMER
    strain_explainer: str = STRAIN_EXPLAINER


def share_out(s: cohort.Share) -> ShareOut:
    return ShareOut(state=s.state, percent=s.percent, text=cohort_report.share_text(s))


def analytics_out(view: teacher_portal.GroupView) -> AnalyticsOut:
    a = view.figures.analytics
    return AnalyticsOut(
        label=view.label,
        scope=view.scope,
        window_weeks=view.weeks,
        state=a.state,
        students_contributing=a.contributors_band,
        min_group_size=cohort.MIN_COHORT,
        weeks=[
            WeekOut(
                week_start=w.week_start,
                students_reporting=w.reporting_band,
                mood=w.mood,
                energy=w.energy,
                stress=w.stress,
                sleep_hours=w.sleep_hours,
                sleep_quality=w.sleep_quality,
                check_in=share_out(w.check_in),
                academic_stress=share_out(w.academic_stress),
                strain=share_out(w.strain),
            )
            for w in a.weeks
        ],
        stressors=[StressorOut(key=k, share=share_out(s)) for k, s in a.stressors],
        wellbeing=[_band(b) for b in view.figures.wellbeing],
        actions=[ActionOut(key=x.key, title=x.title, message=x.message) for x in a.actions],
        headline=cohort_report.headline(a),
        generated_at=view.generated_at,
    )


def _band(b: cohort_stats.WellbeingBand) -> BandOut:
    return BandOut(key=b.key, label=b.label, share=share_out(b.share))


class ClassAnalyticsOut(BaseModel):
    group: ClassOut
    analytics: AnalyticsOut


class DepartmentAnalyticsOut(BaseModel):
    department_id: uuid.UUID
    analytics: AnalyticsOut


# ---- dashboard ------------------------------------------------------------------------------


class ReferralCountsOut(BaseModel):
    received: int
    in_progress: int
    closed: int


class DashboardOut(BaseModel):
    teacher: TeacherOut
    classes: list[ClassOut]
    department: AnalyticsOut
    referrals: ReferralCountsOut
    open_support_requests: int
    new_support_requests: int


def dashboard_out(d: teacher_portal.Dashboard) -> DashboardOut:
    by = {s.value: n for s, n in d.referrals_by_status.items()}
    return DashboardOut(
        teacher=teacher_out(d.context),
        classes=[class_out(c) for c in d.classes],
        department=analytics_out(d.department),
        referrals=ReferralCountsOut(
            received=by["received"], in_progress=by["in_progress"], closed=by["closed"]
        ),
        open_support_requests=d.open_support_requests,
        new_support_requests=d.unread_support_requests,
    )


# ---- referrals ------------------------------------------------------------------------------


class ReferralIn(BaseModel):
    student_id: uuid.UUID
    course_id: uuid.UUID
    category: ReferralCategory
    urgency: ReferralUrgency = ReferralUrgency.ROUTINE
    note: Note | None = None


class ReferralOut(BaseModel):
    """What the teacher who raised a referral sees: their own words and a status."""

    id: uuid.UUID
    student_id: uuid.UUID
    student_name: str
    course_id: uuid.UUID
    course_code: str
    course_title: str
    category: str
    category_label: str
    urgency: str
    urgency_label: str
    note: str | None
    status: str
    status_label: str
    created_at: dt.datetime


class ReferralDetailOut(ReferralOut):
    message: str = (
        "The wellbeing team handles referrals in confidence, so you will see only whether it "
        "has been received, is with someone, or is closed."
    )


def referral_out(v: referrals.ReferralView) -> ReferralOut:
    r = v.referral
    return ReferralOut(
        id=r.id,
        student_id=r.student_id,
        student_name=v.student_name,
        course_id=r.course_id,
        course_code=v.course_code,
        course_title=v.course_title,
        category=r.category.value,
        category_label=CATEGORY_LABELS[r.category],
        urgency=r.urgency.value,
        urgency_label=URGENCY_LABELS[r.urgency],
        note=r.note,
        status=r.status.value,
        status_label=referrals.TEACHER_STATUS_LABELS[r.status],
        created_at=r.created_at,
    )


def referral_detail_out(v: referrals.ReferralView) -> ReferralDetailOut:
    return ReferralDetailOut(**referral_out(v).model_dump())


class TriageReferralOut(ReferralOut):
    """The therapist's view of a referral in the queue."""

    teacher_name: str
    department_name: str
    on_my_team: bool
    claimed_by_me: bool
    outcome: str | None
    outcome_label: str | None
    closed_at: dt.datetime | None
    claimed_at: dt.datetime | None


class CloseIn(BaseModel):
    outcome: ReferralOutcome


def triage_out(v: referrals.TriageView, actor_id: uuid.UUID) -> TriageReferralOut:
    r = v.referral
    return TriageReferralOut(
        **referral_out(v).model_dump(),
        teacher_name=v.teacher_name,
        department_name=v.department_name,
        on_my_team=v.on_my_team,
        claimed_by_me=r.claimed_by == actor_id,
        outcome=r.outcome.value if r.outcome else None,
        outcome_label=OUTCOME_LABELS[r.outcome] if r.outcome else None,
        closed_at=r.closed_at,
        claimed_at=r.claimed_at,
    )


# ---- support requests -----------------------------------------------------------------------


class SupportRequestIn(BaseModel):
    course_id: uuid.UUID
    teacher_id: uuid.UUID
    topic: TeacherSupportTopic
    message: Message | None = None


class SupportRequestOut(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    course_code: str
    course_title: str
    teacher_name: str
    student_name: str
    topic: str
    topic_label: str
    message: str | None
    status: str
    status_label: str
    created_at: dt.datetime


def support_request_out(v: teacher_support.RequestView) -> SupportRequestOut:
    r = v.request
    return SupportRequestOut(
        id=r.id,
        course_id=r.course_id,
        course_code=v.course_code,
        course_title=v.course_title,
        teacher_name=v.teacher_name,
        student_name=v.student_name,
        topic=r.topic.value,
        topic_label=TOPIC_LABELS[r.topic],
        message=r.message,
        status=r.status.value,
        status_label=STATUS_LABELS[r.status.value],
        created_at=r.created_at,
    )


class TeacherOptionOut(BaseModel):
    teacher_id: uuid.UUID
    name: str
    title: str | None


class CourseOptionOut(BaseModel):
    course_id: uuid.UUID
    code: str
    title: str
    teachers: list[TeacherOptionOut]


def course_option_out(c: teacher_support.CourseOption) -> CourseOptionOut:
    return CourseOptionOut(
        course_id=c.course_id,
        code=c.code,
        title=c.title,
        teachers=[
            TeacherOptionOut(teacher_id=t.teacher_id, name=t.name, title=t.title)
            for t in c.teachers
        ],
    )


# ---- report ---------------------------------------------------------------------------------


class ReportOut(BaseModel):
    title: str
    generated_at: dt.datetime
    window_weeks: int
    summary: list[str]
    analytics: AnalyticsOut
    notes: list[str]


REPORT_NOTES = [
    "This report contains no names, scores or messages for any person.",
    "Only students who chose to share anonymous summaries are counted.",
    f"Groups of fewer than {cohort.MIN_COHORT} students are not shown, and percentages are "
    "rounded to the nearest 5.",
    "Please do not use these figures to work out how any one student is doing.",
]


def report_out(view: teacher_portal.GroupView) -> ReportOut:
    analytics = analytics_out(view)
    return ReportOut(
        title=f"Anonymous wellbeing report: {view.label}",
        generated_at=view.generated_at,
        window_weeks=view.weeks,
        summary=analytics.headline,
        analytics=analytics,
        notes=REPORT_NOTES,
    )
