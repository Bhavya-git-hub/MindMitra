"""Request and response bodies for the therapist portal API (snake_case, ISO 8601 UTC).

Deliberately absent from every response here: licence numbers of other people, student
contact details, message bodies, and therapy-note text (which only the dedicated note
endpoints return, to the authoring therapist).
"""

import datetime as dt
import uuid
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints

from app.application import (
    follow_ups,
    risk_alerts,
    therapist_appointments,
    therapist_dashboard,
    therapist_profile,
    therapist_recommendations,
    therapist_students,
    therapy_sessions,
)
from app.application.student_wellness import DailyPoint
from app.application.therapist_access import VERIFICATION_LABELS, effective_verification
from app.infrastructure.db import models as m

Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]

# Plain-language alert wording. These describe why a person should reach out; they are never
# a conclusion about the student.
ALERT_CATEGORY_LABELS = {
    "self_harm_language": "Words about hurting themselves",
    "suicidal_language": "Words about not wanting to be here",
    "harm_to_others": "Words about hurting someone else",
    "unsafe_situation": "May be in an unsafe situation",
    "acute_distress": "Seems very distressed",
    "sustained_low_wellbeing": "Low wellbeing for a while",
    "engagement_drop": "Has gone quiet lately",
}
ALERT_SOURCE_LABELS = {
    "help_button": "Asked for help",
    "mood_entry": "From a check-in",
    "journal": "From a journal entry",
    "ai_chat": "From the assistant",
    "message": "From a message",
    "faculty_referral": "Referred by staff",
    "model": "Flagged by a safety check",
    "therapist": "Raised by a therapist",
}
ALERT_DISCLAIMER = (
    "An alert is a prompt for a person to reach out. It is not a diagnosis or a prediction."
)


# ---- profile and verification ---------------------------------------------------------------


class ProfileOut(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    bio: str | None
    specialties: list[str]
    languages: list[str]
    accepting_new_students: bool
    max_caseload: int
    licence_number: str
    licence_body: str | None
    licence_expires_on: dt.date | None
    verification_status: str
    verification_label: str
    verified_at: dt.datetime | None
    verification_note: str | None
    can_see_students: bool


def profile_out(t: m.Therapist, u: m.User) -> ProfileOut:
    status = effective_verification(t)
    return ProfileOut(
        id=t.user_id,
        full_name=u.full_name,
        email=u.email,
        bio=t.bio,
        specialties=list(t.specialties),
        languages=list(t.languages),
        accepting_new_students=t.accepting_new_students,
        max_caseload=t.max_caseload,
        licence_number=t.licence_number,
        licence_body=t.licence_body,
        licence_expires_on=t.licence_expires_on,
        verification_status=status,
        verification_label=VERIFICATION_LABELS[status],
        verified_at=t.verified_at,
        verification_note=t.verification_note,
        can_see_students=status == "verified",
    )


class ProfileIn(BaseModel):
    bio: str | None = Field(default=None, max_length=2000)
    specialties: list[Tag] | None = Field(default=None, max_length=8)
    languages: list[Tag] | None = Field(default=None, max_length=8)
    accepting_new_students: bool | None = None
    max_caseload: int | None = Field(default=None, ge=1, le=500)


class VerificationIn(BaseModel):
    licence_number: str = Field(min_length=3, max_length=60)
    licence_body: str | None = Field(default=None, max_length=120)
    licence_expires_on: dt.date | None = None


class VerificationReviewIn(BaseModel):
    status: Literal["verified", "rejected", "pending"]
    note: str | None = Field(default=None, max_length=300)
    licence_expires_on: dt.date | None = None


class TherapistReviewOut(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    licence_number: str
    licence_body: str | None
    licence_expires_on: dt.date | None
    verification_status: str
    verified_at: dt.datetime | None
    verification_note: str | None


def review_out(t: m.Therapist, u: m.User) -> TherapistReviewOut:
    return TherapistReviewOut(
        id=t.user_id,
        full_name=u.full_name,
        email=u.email,
        licence_number=t.licence_number,
        licence_body=t.licence_body,
        licence_expires_on=t.licence_expires_on,
        verification_status=effective_verification(t),
        verified_at=t.verified_at,
        verification_note=t.verification_note,
    )


# ---- availability ---------------------------------------------------------------------------


class AvailabilityIn(BaseModel):
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    mode: Literal["video", "in_person", "phone"] = "video"
    repeat_weeks: int = Field(default=0, ge=0, le=11)


class SlotOut(BaseModel):
    id: uuid.UUID
    starts_at: dt.datetime
    ends_at: dt.datetime
    mode: str
    booked: bool
    appointment_id: uuid.UUID | None
    appointment_status: str | None


def slot_out(v: therapist_profile.SlotView) -> SlotOut:
    return SlotOut(
        id=v.slot.id,
        starts_at=v.slot.starts_at,
        ends_at=v.slot.ends_at,
        mode=v.slot.mode.value,
        booked=v.appointment_id is not None,
        appointment_id=v.appointment_id,
        appointment_status=v.appointment_status.value if v.appointment_status else None,
    )


# ---- appointments and sessions --------------------------------------------------------------


class TherapistAppointmentOut(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    therapist_id: uuid.UUID
    student_name: str
    starts_at: dt.datetime
    ends_at: dt.datetime
    mode: str
    status: str
    reason: str | None
    session_id: uuid.UUID | None


def appointment_row_out(r: therapist_appointments.AppointmentRow) -> TherapistAppointmentOut:
    a = r.appointment
    return TherapistAppointmentOut(
        id=a.id,
        student_id=a.student_id,
        therapist_id=a.therapist_id,
        student_name=r.student_name,
        starts_at=a.starts_at,
        ends_at=a.ends_at,
        mode=a.mode.value,
        status=a.status.value,
        reason=a.reason,
        session_id=r.session_id,
    )


class SessionOut(BaseModel):
    id: uuid.UUID
    appointment_id: uuid.UUID
    student_id: uuid.UUID
    student_name: str
    status: str
    started_at: dt.datetime
    ended_at: dt.datetime | None
    duration_minutes: int | None
    scheduled_start: dt.datetime
    scheduled_end: dt.datetime
    mode: str
    has_note: bool


def session_out(v: therapy_sessions.SessionView) -> SessionOut:
    s = v.session
    return SessionOut(
        id=s.id,
        appointment_id=s.appointment_id,
        student_id=s.student_id,
        student_name=v.student_name,
        status=s.status.value,
        started_at=s.started_at,
        ended_at=s.ended_at,
        duration_minutes=s.duration_minutes,
        scheduled_start=v.appointment.starts_at,
        scheduled_end=v.appointment.ends_at,
        mode=v.appointment.mode.value,
        has_note=v.note_versions > 0,
    )


class SessionFinishIn(BaseModel):
    status: Literal["completed", "abandoned"]


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=therapy_sessions.MAX_NOTE_LENGTH)


class NoteVersionOut(BaseModel):
    version: int
    written_at: dt.datetime


class NoteOut(BaseModel):
    """Confidential: only the authoring therapist is ever sent this."""

    session_id: uuid.UUID
    version: int
    body: str
    written_at: dt.datetime
    latest: bool
    versions: list[NoteVersionOut]


def note_out(v: therapy_sessions.NoteView) -> NoteOut:
    n = v.note
    return NoteOut(
        session_id=n.session_id,
        version=n.version,
        body=n.body,
        written_at=n.created_at,
        latest=n.version == max(ver for ver, _ in v.versions),
        versions=[NoteVersionOut(version=ver, written_at=at) for ver, at in v.versions],
    )


# ---- students -------------------------------------------------------------------------------


class SharingOut(BaseModel):
    mood: bool
    assessments: bool


class CaseloadStudentOut(BaseModel):
    student_id: uuid.UUID
    full_name: str
    preferred_name: str | None
    year_of_study: int
    care_role: str
    since: dt.datetime
    next_appointment_at: dt.datetime | None
    last_session_at: dt.datetime | None
    open_alerts: int
    open_follow_ups: int
    sharing: SharingOut


def caseload_out(r: therapist_students.CaseloadRow) -> CaseloadStudentOut:
    return CaseloadStudentOut(
        student_id=r.student.user_id,
        full_name=r.name,
        preferred_name=r.student.preferred_name,
        year_of_study=r.student.year_of_study,
        care_role=r.care_role.value,
        since=r.since,
        next_appointment_at=r.next_appointment.starts_at if r.next_appointment else None,
        last_session_at=r.last_session_at,
        open_alerts=r.open_alerts,
        open_follow_ups=r.open_follow_ups,
        sharing=SharingOut(mood=r.sharing.mood, assessments=r.sharing.assessments),
    )


class ProfileSessionOut(BaseModel):
    id: uuid.UUID
    status: str
    started_at: dt.datetime
    duration_minutes: int | None
    has_note: bool


class LatestMoodOut(BaseModel):
    score: int
    logged_at: dt.datetime


class LatestAssessmentOut(BaseModel):
    score: float
    max_score: float
    completed_at: dt.datetime


class StudentProfileOut(BaseModel):
    student_id: uuid.UUID
    full_name: str
    preferred_name: str | None
    pronouns: str | None
    department: str
    year_of_study: int
    care_role: str
    since: dt.datetime
    sharing: SharingOut
    upcoming_appointments: list[TherapistAppointmentOut]
    recent_sessions: list[ProfileSessionOut]
    open_alerts: int
    open_follow_ups: int
    latest_mood: LatestMoodOut | None
    latest_assessment: LatestAssessmentOut | None
    disclaimer: str = (
        "Check-in figures are what the student chose to share. They are not a diagnosis."
    )


def student_profile_out(p: therapist_students.StudentProfile) -> StudentProfileOut:
    return StudentProfileOut(
        student_id=p.student.user_id,
        full_name=p.name,
        preferred_name=p.student.preferred_name,
        pronouns=p.student.pronouns,
        department=p.department,
        year_of_study=p.student.year_of_study,
        care_role=p.care_role.value,
        since=p.since,
        sharing=SharingOut(mood=p.sharing.mood, assessments=p.sharing.assessments),
        upcoming_appointments=[
            TherapistAppointmentOut(
                id=a.id,
                student_id=a.student_id,
                therapist_id=a.therapist_id,
                student_name=p.name,
                starts_at=a.starts_at,
                ends_at=a.ends_at,
                mode=a.mode.value,
                status=a.status.value,
                reason=a.reason,
                session_id=None,
            )
            for a in p.upcoming
        ],
        recent_sessions=[
            ProfileSessionOut(
                id=s.session.id,
                status=s.session.status.value,
                started_at=s.session.started_at,
                duration_minutes=s.session.duration_minutes,
                has_note=s.has_note,
            )
            for s in p.sessions
        ],
        open_alerts=p.open_alerts,
        open_follow_ups=p.open_follow_ups,
        latest_mood=LatestMoodOut(score=p.latest_mood.score, logged_at=p.latest_mood.logged_at)
        if p.latest_mood
        else None,
        latest_assessment=LatestAssessmentOut(
            score=p.latest_assessment.score,
            max_score=p.latest_assessment.max_score,
            completed_at=p.latest_assessment.completed_at,
        )
        if p.latest_assessment
        else None,
    )


class TrendPointOut(BaseModel):
    day: dt.date
    mood: float | None
    energy: float | None
    stress: float | None
    sleep_hours: float | None
    sleep_quality: int | None


class TrendsOut(BaseModel):
    days: int
    points: list[TrendPointOut]
    disclaimer: str = (
        "Averages of what the student reported on days they checked in. They are not a diagnosis."
    )


def trends_out(days: int, series: list[DailyPoint]) -> TrendsOut:
    return TrendsOut(
        days=days,
        points=[
            TrendPointOut(
                day=p.day,
                mood=p.mood,
                energy=p.energy,
                stress=p.stress,
                sleep_hours=round(p.sleep_minutes / 60, 1) if p.sleep_minutes is not None else None,
                sleep_quality=p.sleep_quality,
            )
            for p in series
        ],
    )


class AssessmentOut(BaseModel):
    id: uuid.UUID
    instrument: str
    score: float
    max_score: float
    completed_at: dt.datetime


def assessment_out(a: m.WellnessAssessment) -> AssessmentOut:
    return AssessmentOut(
        id=a.id,
        instrument=a.instrument,
        score=float(a.score),
        max_score=float(a.max_score),
        completed_at=a.completed_at,
    )


# ---- alerts ---------------------------------------------------------------------------------


class AlertOut(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    student_name: str
    severity: str
    status: str
    category: str
    category_label: str
    source_label: str
    created_at: dt.datetime
    sla_ack_due_at: dt.datetime | None
    acknowledged_at: dt.datetime | None
    resolved_at: dt.datetime | None
    outcome: str | None
    assigned_to_me: bool
    overdue: bool
    excerpt: str | None
    disclaimer: str = ALERT_DISCLAIMER


def alert_out(v: risk_alerts.AlertView) -> AlertOut:
    a = v.alert
    return AlertOut(
        id=a.id,
        student_id=a.student_id,
        student_name=v.student_name,
        severity=a.severity.value,
        status=a.status.value,
        category=a.category.value,
        category_label=ALERT_CATEGORY_LABELS.get(a.category.value, "Needs a person to check in"),
        source_label=ALERT_SOURCE_LABELS.get(a.source.value, "Flagged"),
        created_at=a.created_at,
        sla_ack_due_at=a.sla_ack_due_at,
        acknowledged_at=a.acknowledged_at,
        resolved_at=a.resolved_at,
        outcome=a.outcome,
        assigned_to_me=v.assigned_to_me,
        overdue=v.overdue,
        excerpt=a.excerpt,
    )


class AlertActionIn(BaseModel):
    action: Literal["acknowledge", "start", "resolve"]
    outcome: (
        Literal[
            "contacted_student",
            "session_booked",
            "referred_elsewhere",
            "emergency_services",
            "no_action_needed",
        ]
        | None
    ) = None


# ---- follow-ups -----------------------------------------------------------------------------


class FollowUpIn(BaseModel):
    student_id: uuid.UUID
    kind: Literal["check_in", "book_session", "referral", "paperwork", "other"]
    due_on: dt.date
    note: str | None = Field(default=None, max_length=follow_ups.MAX_NOTE)
    session_id: uuid.UUID | None = None


class FollowUpPatchIn(BaseModel):
    status: Literal["open", "done", "cancelled"] | None = None
    due_on: dt.date | None = None
    note: str | None = Field(default=None, max_length=follow_ups.MAX_NOTE)


class FollowUpOut(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    student_name: str
    session_id: uuid.UUID | None
    kind: str
    status: str
    due_on: dt.date
    note: str | None
    completed_at: dt.datetime | None
    overdue: bool


def follow_up_out(v: follow_ups.FollowUpView) -> FollowUpOut:
    f = v.follow_up
    return FollowUpOut(
        id=f.id,
        student_id=f.student_id,
        student_name=v.student_name,
        session_id=f.session_id,
        kind=f.kind.value,
        status=f.status.value,
        due_on=f.due_on,
        note=f.note,
        completed_at=f.completed_at,
        overdue=v.overdue,
    )


# ---- recommendations ------------------------------------------------------------------------


class RecommendationIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    rationale: str = Field(min_length=3, max_length=600)
    resource_id: uuid.UUID | None = None


class MadeRecommendationOut(BaseModel):
    id: uuid.UUID
    title: str
    rationale: str
    status: str
    resource_id: uuid.UUID | None
    resource_title: str | None
    created_at: dt.datetime
    expires_at: dt.datetime | None


def made_out(v: therapist_recommendations.MadeRecommendation) -> MadeRecommendationOut:
    r = v.recommendation
    return MadeRecommendationOut(
        id=r.id,
        title=r.title,
        rationale=r.rationale,
        status=r.status.value,
        resource_id=r.resource_id,
        resource_title=v.resource.title if v.resource else None,
        created_at=r.created_at,
        expires_at=r.expires_at,
    )


# ---- dashboard ------------------------------------------------------------------------------


class DashboardOut(BaseModel):
    verification_status: str
    verification_label: str
    can_see_students: bool
    accepting_new_students: bool
    caseload: int
    max_caseload: int
    today: list[TherapistAppointmentOut]
    next_appointment: TherapistAppointmentOut | None
    pending_requests: int
    alerts_by_severity: dict[str, int]
    alerts_overdue: int
    follow_ups_due_today: int
    follow_ups_overdue: int
    unread_messages: int


def dashboard_out(d: therapist_dashboard.Dashboard) -> DashboardOut:
    return DashboardOut(
        verification_status=d.verification,
        verification_label=VERIFICATION_LABELS[d.verification],
        can_see_students=d.verification == "verified",
        accepting_new_students=d.therapist.accepting_new_students,
        caseload=d.caseload,
        max_caseload=d.therapist.max_caseload,
        today=[appointment_row_out(r) for r in d.today],
        next_appointment=appointment_row_out(d.next_appointment) if d.next_appointment else None,
        pending_requests=d.pending_requests,
        alerts_by_severity=d.alerts_by_severity,
        alerts_overdue=d.alerts_overdue,
        follow_ups_due_today=d.follow_ups_due_today,
        follow_ups_overdue=d.follow_ups_overdue,
        unread_messages=d.unread_messages,
    )
