"""Request and response bodies for the student portal API (snake_case, ISO 8601 UTC)."""

import datetime as dt
import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints

from app.application import (
    booking,
    recommendation_feedback,
    recommendations,
    safety_workflow,
    student_analytics,
)
from app.application.student_wellness import DailyPoint, Summary
from app.domain.wellness import indicators, instruments
from app.domain.wellness.recommender.catalog import BY_KEY, MUTABLE_AREAS
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import CancellationReason, GoalCategory, TherapySessionStatus

Score = Annotated[int, Field(ge=1, le=5)]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]

DISCLAIMER = (
    "These figures describe what you reported. They are not a diagnosis or a clinical assessment."
)


# ---- check-in and tracking ------------------------------------------------------------------


class SleepIn(BaseModel):
    bedtime: AwareDatetime
    wake_time: AwareDatetime
    quality: Score


class CheckInIn(BaseModel):
    mood_score: Score
    energy_level: Score | None = None
    emotions: list[Label] = Field(default_factory=list, max_length=8)
    note: str | None = Field(default=None, max_length=2000)
    stress_level: Score | None = None
    stressors: list[Label] = Field(default_factory=list, max_length=8)
    sleep: SleepIn | None = None


class MoodEntryIn(BaseModel):
    mood_score: Score
    energy_level: Score | None = None
    emotions: list[Label] = Field(default_factory=list, max_length=8)
    note: str | None = Field(default=None, max_length=2000)


class StressEntryIn(BaseModel):
    stress_level: Score
    stressors: list[Label] = Field(default_factory=list, max_length=8)


class StressEntryOut(BaseModel):
    id: uuid.UUID
    stress_level: int
    stressors: list[str]
    logged_at: dt.datetime


def stress_out(r: m.StressAssessment) -> StressEntryOut:
    return StressEntryOut(
        id=r.id,
        stress_level=r.perceived_stress_level,
        stressors=list(r.stressors),
        logged_at=r.completed_at,
    )


class SleepEntryOut(BaseModel):
    id: uuid.UUID
    sleep_date: dt.date
    bedtime: dt.datetime
    wake_time: dt.datetime
    duration_minutes: int
    quality: int


def sleep_out(r: m.SleepEntry) -> SleepEntryOut:
    return SleepEntryOut(
        id=r.id,
        sleep_date=r.sleep_date,
        bedtime=r.bedtime,
        wake_time=r.wake_time,
        duration_minutes=r.duration_minutes,
        quality=r.quality,
    )


class SupportInfo(BaseModel):
    message: str
    help_path: str


SUPPORT_INFO = SupportInfo(
    message=(
        "Thank you for telling us. If things feel heavy, you don't have to carry them alone. "
        "You can reach someone right now."
    ),
    help_path="/student/emergency",
)


# ---- safety (ADR 0013) ----------------------------------------------------------------------


class EmergencyResourceOut(BaseModel):
    id: uuid.UUID | None  # null for the built-in "local emergency services" entry
    label: str
    kind: str  # "emergency" | "helpline" | "campus"
    phone: str | None
    url: str | None
    description: str | None
    hours: str | None


class GuidanceOut(BaseModel):
    title: str
    message: str
    steps: list[str]


class CounsellingAccessOut(BaseModel):
    has_care_team: bool
    message_path: str | None
    booking_path: str


class HumanEscalationOut(BaseModel):
    # "requested" | "already_open" | "not_requested" | "failed"
    status: str
    # "consent" | "vital_interest" | "care_team_message" | "companion_notice" | "no_consent"
    # | "not_needed"
    basis: str
    care_team_notified: bool


class SafetyOut(BaseModel):
    """What to show when words or numbers suggest a student may need support. Never a
    diagnosis; never a replacement for emergency services or qualified professionals."""

    level: str  # "moderate" | "high" | "immediate"
    about_someone_else: bool
    emergency_first: bool
    offer_outreach: bool  # nobody was asked automatically: offer "ask someone to reach out"
    guidance: GuidanceOut
    resources: list[EmergencyResourceOut]
    counselling: CounsellingAccessOut
    escalation: HumanEscalationOut
    recommendations_paused: bool
    paused_until: dt.datetime | None
    disclaimer: str


class SafetyStatusOut(BaseModel):
    recommendations_paused: bool
    support: SafetyOut | None  # present while suggestions are paused
    disclaimer: str


def safety_out(o: safety_workflow.SafetyOutcome) -> SafetyOut:
    failed = o.escalation.status is safety_workflow.EscalationStatus.FAILED
    return SafetyOut(
        level=o.level.value,
        about_someone_else=o.about_someone_else,
        emergency_first=o.decision.emergency_first,
        offer_outreach=o.decision.offer_outreach or failed,
        guidance=GuidanceOut(
            title=o.guidance.title, message=o.guidance.message, steps=list(o.guidance.steps)
        ),
        resources=[
            EmergencyResourceOut(
                id=r.id,
                label=r.label,
                kind=r.kind,
                phone=r.phone,
                url=r.url,
                description=r.description,
                hours=r.hours,
            )
            for r in o.resources
        ],
        counselling=CounsellingAccessOut(
            has_care_team=o.counselling.has_care_team,
            message_path=o.counselling.message_path,
            booking_path=o.counselling.booking_path,
        ),
        escalation=HumanEscalationOut(
            status=o.escalation.status.value,
            basis=o.escalation.basis.value,
            care_team_notified=o.escalation.care_team_notified,
        ),
        recommendations_paused=o.recommendations_paused,
        paused_until=o.hold_until,
        disclaimer=o.disclaimer,
    )


# ---- indicators, summary, trends ------------------------------------------------------------


class IndicatorOut(BaseModel):
    key: str
    label: str


def _indicator(i: indicators.Indicator | None) -> IndicatorOut | None:
    return IndicatorOut(key=i.key, label=i.label) if i else None


class MetricOut(BaseModel):
    today: float | None
    average_7d: float | None
    indicator: IndicatorOut | None
    direction: Literal["up", "steady", "down"] | None


class SleepMetricOut(BaseModel):
    last_night_minutes: int | None
    last_night_quality: int | None
    average_minutes_7d: float | None
    indicator: IndicatorOut | None
    direction: Literal["up", "steady", "down"] | None


class CheckInStatusOut(BaseModel):
    done_today: bool
    streak_days: int
    check_ins_last_7d: int
    days_since_last: int | None
    emotions_today: list[str]


class BandOut(BaseModel):
    key: str
    label: str
    message: str


class AssessmentSnapshotOut(BaseModel):
    id: uuid.UUID
    score: float
    max_score: float
    percent: int
    band: BandOut
    completed_at: dt.datetime


def assessment_out(r: m.WellnessAssessment) -> AssessmentSnapshotOut:
    b = instruments.band(float(r.score))
    return AssessmentSnapshotOut(
        id=r.id,
        score=float(r.score),
        max_score=float(r.max_score),
        percent=instruments.percentage(float(r.score)),
        band=BandOut(key=b.key, label=b.label, message=b.message),
        completed_at=r.completed_at,
    )


class WellnessSummaryOut(BaseModel):
    date: dt.date
    check_in: CheckInStatusOut
    mood: MetricOut
    stress: MetricOut
    sleep: SleepMetricOut
    wellbeing: AssessmentSnapshotOut | None
    active_goals: int
    disclaimer: str = DISCLAIMER


def summary_out(s: Summary) -> WellnessSummaryOut:
    last = s.sleep_last_night
    return WellnessSummaryOut(
        date=s.today,
        check_in=CheckInStatusOut(
            done_today=s.checked_in_today,
            streak_days=s.streak_days,
            check_ins_last_7d=s.check_ins_last_7d,
            days_since_last=s.days_since_check_in,
            emotions_today=s.mood_today_emotions,
        ),
        mood=MetricOut(
            today=s.mood_today,
            average_7d=s.avg_mood_7d,
            indicator=_indicator(indicators.mood_indicator(s.mood_today or s.avg_mood_7d)),
            direction=s.mood_direction,  # type: ignore[arg-type]
        ),
        stress=MetricOut(
            today=s.stress_today,
            average_7d=s.avg_stress_7d,
            indicator=_indicator(indicators.stress_indicator(s.stress_today or s.avg_stress_7d)),
            direction=s.stress_direction,  # type: ignore[arg-type]
        ),
        sleep=SleepMetricOut(
            last_night_minutes=last.duration_minutes if last else None,
            last_night_quality=last.quality if last else None,
            average_minutes_7d=s.avg_sleep_minutes_7d,
            indicator=_indicator(
                indicators.sleep_indicator(
                    last.duration_minutes if last else s.avg_sleep_minutes_7d
                )
            ),
            direction=s.sleep_direction,  # type: ignore[arg-type]
        ),
        wellbeing=assessment_out(s.latest_assessment) if s.latest_assessment else None,
        active_goals=s.active_goals,
    )


class TrendPointOut(BaseModel):
    date: dt.date
    mood: float | None
    energy: float | None
    stress: float | None
    sleep_minutes: int | None
    sleep_quality: int | None


def trend_out(p: DailyPoint) -> TrendPointOut:
    return TrendPointOut(
        date=p.day,
        mood=p.mood,
        energy=p.energy,
        stress=p.stress,
        sleep_minutes=p.sleep_minutes,
        sleep_quality=p.sleep_quality,
    )


class TrendsOut(BaseModel):
    days: int
    points: list[TrendPointOut]
    disclaimer: str = DISCLAIMER


# ---- analytics ------------------------------------------------------------------------------


class WeekOut(BaseModel):
    week_start: dt.date  # the Monday, in the student's own time zone
    wellness_index: int | None  # 0-100, from what the student reported
    mood_avg: float | None
    stress_avg: float | None
    sleep_quality_avg: float | None
    sleep_hours_avg: float | None
    days_reported: int = Field(ge=0, le=7)
    partial: bool  # the current week is not over yet


class WellbeingCheckOut(BaseModel):
    completed_at: dt.datetime
    percent: int
    band: BandOut


class CategoryProgressOut(BaseModel):
    category: str
    active: int
    completed: int
    average_progress_percent: float | None


class WeekCompletedOut(BaseModel):
    week_start: dt.date
    completed: int


class GoalAnalyticsOut(BaseModel):
    active: int
    completed: int
    other: int  # paused or set aside
    average_progress_percent: float | None  # active goals that have a target
    by_category: list[CategoryProgressOut]
    completed_by_week: list[WeekCompletedOut]


class WellnessAnalyticsOut(BaseModel):
    weeks: list[WeekOut]  # oldest first, ending with the current (partial) week
    wellbeing_checks: list[WellbeingCheckOut]  # the last 12, oldest first
    goals: GoalAnalyticsOut
    disclaimer: str = DISCLAIMER


def analytics_out(a: student_analytics.StudentAnalytics) -> WellnessAnalyticsOut:
    return WellnessAnalyticsOut(
        weeks=[WeekOut(**vars(w)) for w in a.weeks],
        wellbeing_checks=[
            WellbeingCheckOut(
                completed_at=r.completed_at,
                percent=instruments.percentage(float(r.score)),
                band=BandOut(**vars(instruments.band(float(r.score)))),
            )
            for r in a.wellbeing_checks
        ],
        goals=GoalAnalyticsOut(
            active=a.goals.active,
            completed=a.goals.completed,
            other=a.goals.other,
            average_progress_percent=a.goals.average_progress_percent,
            by_category=[
                CategoryProgressOut(
                    category=c.category.value,
                    active=c.active,
                    completed=c.completed,
                    average_progress_percent=c.average_progress_percent,
                )
                for c in a.goals.by_category
            ],
            completed_by_week=[
                WeekCompletedOut(week_start=w.week_start, completed=w.completed)
                for w in a.goals.completed_by_week
            ],
        ),
    )


# ---- assessment -----------------------------------------------------------------------------


class QuestionOut(BaseModel):
    key: str
    text: str


class OptionOut(BaseModel):
    value: int
    label: str


class InstrumentOut(BaseModel):
    id: str
    version: str
    title: str
    intro: str
    attribution: str
    disclaimer: str
    options: list[OptionOut]
    questions: list[QuestionOut]


def instrument_out() -> InstrumentOut:
    return InstrumentOut(
        id=instruments.INSTRUMENT_ID,
        version=instruments.INSTRUMENT_VERSION,
        title=instruments.INSTRUMENT_TITLE,
        intro=instruments.INSTRUMENT_INTRO,
        attribution=instruments.ATTRIBUTION,
        disclaimer=instruments.DISCLAIMER,
        options=[OptionOut(value=v, label=label) for v, label in instruments.OPTIONS],
        questions=[QuestionOut(key=q.key, text=q.text) for q in instruments.QUESTIONS],
    )


class AssessmentIn(BaseModel):
    responses: dict[str, Annotated[int, Field(ge=0, le=5)]]


# ---- goals ----------------------------------------------------------------------------------


class GoalIn(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    category: GoalCategory
    description: str | None = Field(default=None, max_length=1000)
    target_value: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    unit: str | None = Field(default=None, max_length=30)
    target_date: dt.date | None = None


class GoalPatchIn(BaseModel):
    title: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
        | None
    ) = None
    description: str | None = Field(default=None, max_length=1000)
    current_value: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    target_value: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    target_date: dt.date | None = None
    status: Literal["active", "paused", "completed", "abandoned"] | None = None


class GoalOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    category: str
    status: str
    target_value: float | None
    current_value: float
    unit: str | None
    progress_percent: int | None
    start_date: dt.date
    target_date: dt.date | None
    completed_at: dt.datetime | None


def goal_out(g: m.WellnessGoal) -> GoalOut:
    progress = indicators.goal_progress_percent(
        float(g.current_value), None if g.target_value is None else float(g.target_value)
    )
    return GoalOut(
        id=g.id,
        title=g.title,
        description=g.description,
        category=g.category.value,
        status=g.status.value,
        target_value=float(g.target_value) if g.target_value is not None else None,
        current_value=float(g.current_value),
        unit=g.unit,
        progress_percent=progress,
        start_date=g.start_date,
        target_date=g.target_date,
        completed_at=g.completed_at,
    )


# ---- resources and recommendations ----------------------------------------------------------


class ResourceOut(BaseModel):
    id: uuid.UUID
    title: str
    summary: str
    resource_type: str
    tags: list[str]
    duration_minutes: int | None
    url: str | None


class ResourceDetailOut(ResourceOut):
    body: str | None


def resource_out(r: m.Resource) -> ResourceOut:
    return ResourceOut(
        id=r.id,
        title=r.title,
        summary=r.summary,
        resource_type=r.resource_type.value,
        tags=list(r.tags),
        duration_minutes=r.duration_minutes,
        url=r.url,
    )


def resource_detail_out(r: m.Resource) -> ResourceDetailOut:
    return ResourceDetailOut(**resource_out(r).model_dump(), body=r.body)


class RecommendationFeedbackOut(BaseModel):
    rating: str
    reason: str | None
    updated_at: dt.datetime


class RecommendationOut(BaseModel):
    id: uuid.UUID
    title: str
    rationale: str
    status: str
    source: str
    created_at: dt.datetime
    expires_at: dt.datetime | None
    resource: ResourceOut | None
    # Which part of student life it is about (None for older suggestions and a therapist's).
    problem_area: str | None = None
    # What the student can do with it: open the resource, book counselling, set a goal, check in.
    action: str = "resource"
    goal_category: str | None = None
    feedback: RecommendationFeedbackOut | None = None
    disclaimer: str = "An optional idea based on what you reported. It is not advice."


def recommendation_out(v: recommendations.RecommendationView) -> RecommendationOut:
    r = v.recommendation
    idea = BY_KEY.get(r.intervention_key or "")
    goal_category = (r.reasons or {}).get("goal_category")
    fb = v.feedback
    return RecommendationOut(
        id=r.id,
        title=r.title,
        rationale=r.rationale,
        status=r.status.value,
        source=r.source.value,
        created_at=r.created_at,
        expires_at=r.expires_at,
        resource=resource_out(v.resource) if v.resource else None,
        problem_area=r.problem_area,
        action=idea.action if idea else "resource",
        goal_category=goal_category if isinstance(goal_category, str) else None,
        feedback=RecommendationFeedbackOut(
            rating=fb.rating.value,
            reason=fb.reason.value if fb.reason else None,
            updated_at=fb.updated_at,
        )
        if fb
        else None,
    )


class RecommendationPatchIn(BaseModel):
    status: Literal["viewed", "dismissed", "completed"]


class RecommendationFeedbackIn(BaseModel):
    rating: Literal["helpful", "not_helpful"]
    reason: (
        Literal["not_relevant", "wrong_format", "too_long", "already_doing_this", "not_now"] | None
    ) = None


class RecommendationPreferencesOut(BaseModel):
    preferred_formats: list[str]
    max_minutes: int | None
    muted_areas: list[str]
    use_indicators: bool
    # What can be chosen, so the settings screen needs no list of its own.
    available_formats: list[str]
    available_areas: list[str]


class RecommendationPreferencesPatchIn(BaseModel):
    preferred_formats: list[str] | None = None
    max_minutes: int | None = Field(default=None, ge=1, le=180)
    muted_areas: list[str] | None = None
    use_indicators: bool | None = None


def preferences_out(p: recommendation_feedback.StoredPreferences) -> RecommendationPreferencesOut:
    return RecommendationPreferencesOut(
        preferred_formats=list(p.preferred_formats),
        max_minutes=p.max_minutes,
        muted_areas=list(p.muted_areas),
        use_indicators=p.use_indicators,
        available_formats=list(recommendation_feedback.FORMATS),
        available_areas=list(MUTABLE_AREAS),
    )


# ---- therapists and appointments ------------------------------------------------------------


class TherapistOut(BaseModel):
    id: uuid.UUID
    full_name: str
    specialties: list[str]
    languages: list[str]
    accepting_new_students: bool
    next_available_at: dt.datetime | None
    on_my_care_team: bool


class TherapistDetailOut(TherapistOut):
    bio: str | None


class SlotOut(BaseModel):
    id: uuid.UUID
    starts_at: dt.datetime
    ends_at: dt.datetime
    mode: str


class BookingIn(BaseModel):
    availability_id: uuid.UUID
    reason: str | None = Field(default=None, max_length=1000)


class StudentAppointmentOut(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    therapist_id: uuid.UUID
    therapist_name: str
    starts_at: dt.datetime
    ends_at: dt.datetime
    mode: str
    status: str
    reason: str | None
    can_cancel: bool
    can_reschedule: bool
    cancelled_at: dt.datetime | None
    cancel_reason: CancellationReason | None
    reschedule_count: int
    rescheduled_at: dt.datetime | None
    # The delivered session once the therapist starts it: in_progress, completed or abandoned.
    session_status: TherapySessionStatus | None


def appointment_view_out(v: booking.AppointmentView) -> StudentAppointmentOut:
    a = v.appointment
    return StudentAppointmentOut(
        id=a.id,
        student_id=a.student_id,
        therapist_id=a.therapist_id,
        therapist_name=v.therapist_name,
        starts_at=a.starts_at,
        ends_at=a.ends_at,
        mode=a.mode.value,
        status=a.status.value,
        reason=a.reason,
        can_cancel=v.can_cancel,
        can_reschedule=v.can_reschedule,
        cancelled_at=a.cancelled_at,
        cancel_reason=a.cancel_reason,
        reschedule_count=a.reschedule_count,
        rescheduled_at=a.rescheduled_at,
        session_status=v.session_status,
    )


class AppointmentPatchIn(BaseModel):
    status: Literal["cancelled"]
    reason: CancellationReason | None = None  # optional, and only ever one of a fixed list


class RescheduleIn(BaseModel):
    availability_id: uuid.UUID


# ---- messages -------------------------------------------------------------------------------


class ConversationOut(BaseModel):
    other_id: uuid.UUID
    other_name: str
    active: bool
    last_message_at: dt.datetime | None
    last_message_preview: str | None
    unread_count: int


class MessageOut(BaseModel):
    id: uuid.UUID
    sender_id: uuid.UUID
    mine: bool
    body: str
    created_at: dt.datetime
    read_at: dt.datetime | None


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    client_msg_id: uuid.UUID | None = None


class SentMessageOut(BaseModel):
    message: MessageOut
    support: SupportInfo | None = None
    safety: SafetyOut | None = None


# ---- privacy --------------------------------------------------------------------------------


class ConsentOut(BaseModel):
    scope: str
    title: str
    description: str
    required: bool
    granted: bool
    granted_at: dt.datetime | None
    policy_version: str | None


class ConsentPutIn(BaseModel):
    granted: bool


class AccessEventOut(BaseModel):
    occurred_at: dt.datetime
    actor_role: str | None
    action: str
    resource_type: str | None


class SupportRequestIn(BaseModel):
    message: str | None = Field(default=None, max_length=1000)


class SupportRequestOut(BaseModel):
    id: uuid.UUID
    status: str
    already_open: bool
    reaches_care_team: bool
    created_at: dt.datetime


class CrisisContactOut(BaseModel):
    id: uuid.UUID
    label: str
    kind: str
    phone: str | None
    url: str | None
    description: str | None
    hours: str | None
