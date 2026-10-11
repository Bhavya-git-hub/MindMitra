"""Response body of ``GET /therapist/analytics`` (snake_case, ISO 8601 UTC).

Counts and averages only. Deliberately absent: student ids, names and emails, per-student
values, appointment reasons, alert categories and excerpts, follow-up and therapy-note text,
recommendation titles and rationales, message bodies.
"""

import datetime as dt
import enum

from pydantic import BaseModel

from app.application import therapist_analytics as ta

DISCLAIMER = (
    "These are counts and averages of what students chose to share and of your own work. They "
    "are self-reported, not a diagnosis, and say nothing about any one person."
)


class CaseloadWeekOut(BaseModel):
    week_start: dt.date
    students_reporting: int
    mood_avg: float | None
    stress_avg: float | None
    sleep_hours_avg: float | None


class CaseloadOut(BaseModel):
    caseload_size: int
    sharing_count: int
    weekly: list[CaseloadWeekOut]


class AppointmentWeekOut(BaseModel):
    week_start: dt.date
    scheduled: int
    completed: int
    no_show: int
    cancelled: int


class RatesOut(BaseModel):
    completion: int | None
    no_show: int | None
    cancellation: int | None


class AppointmentsOut(BaseModel):
    by_status: dict[str, int]
    weekly: list[AppointmentWeekOut]
    rates: RatesOut
    by_mode: dict[str, int]


class WeekCountOut(BaseModel):
    week_start: dt.date
    count: int


class RecommendationsOut(BaseModel):
    total: int
    by_status: dict[str, int]
    completion_rate: int | None
    weekly: list[WeekCountOut]


class FollowUpsOut(BaseModel):
    total: int
    by_status: dict[str, int]
    overdue: int
    done_on_time_rate: int | None
    by_kind: dict[str, int]


class InterventionsOut(BaseModel):
    recommendations: RecommendationsOut
    follow_ups: FollowUpsOut


class AlertsOut(BaseModel):
    total: int
    by_severity: dict[str, int]
    by_status: dict[str, int]
    weekly: list[WeekCountOut]
    acknowledged_median_minutes: float | None
    overdue_open: int
    resolved_count: int


class TherapistAnalyticsOut(BaseModel):
    weeks: int
    window_start: dt.date
    window_end: dt.date
    caseload: CaseloadOut
    appointments: AppointmentsOut
    interventions: InterventionsOut
    alerts: AlertsOut
    generated_at: dt.datetime
    disclaimer: str


def _keyed[E: enum.Enum](counts: dict[E, int]) -> dict[str, int]:
    return {str(k.value): n for k, n in counts.items()}


def _weeks(rows: list[ta.WeekCount]) -> list[WeekCountOut]:
    return [WeekCountOut(week_start=w.week_start, count=w.count) for w in rows]


def analytics_out(a: ta.TherapistAnalytics) -> TherapistAnalyticsOut:
    recs, follow = a.interventions.recommendations, a.interventions.follow_ups
    return TherapistAnalyticsOut(
        weeks=a.weeks,
        window_start=a.window_start,
        window_end=a.window_end,
        caseload=CaseloadOut(
            caseload_size=a.caseload.caseload_size,
            sharing_count=a.caseload.sharing_count,
            weekly=[CaseloadWeekOut(**vars(w)) for w in a.caseload.weekly],
        ),
        appointments=AppointmentsOut(
            by_status=_keyed(a.appointments.by_status),
            weekly=[AppointmentWeekOut(**vars(w)) for w in a.appointments.weekly],
            rates=RatesOut(**vars(a.appointments.rates)),
            by_mode=_keyed(a.appointments.by_mode),
        ),
        interventions=InterventionsOut(
            recommendations=RecommendationsOut(
                total=recs.total,
                by_status=_keyed(recs.by_status),
                completion_rate=recs.completion_rate,
                weekly=_weeks(recs.weekly),
            ),
            follow_ups=FollowUpsOut(
                total=follow.total,
                by_status=_keyed(follow.by_status),
                overdue=follow.overdue,
                done_on_time_rate=follow.done_on_time_rate,
                by_kind=_keyed(follow.by_kind),
            ),
        ),
        alerts=AlertsOut(
            total=a.alerts.total,
            by_severity=_keyed(a.alerts.by_severity),
            by_status=_keyed(a.alerts.by_status),
            weekly=_weeks(a.alerts.weekly),
            acknowledged_median_minutes=a.alerts.acknowledged_median_minutes,
            overdue_open=a.alerts.overdue_open,
            resolved_count=a.alerts.resolved_count,
        ),
        generated_at=a.generated_at,
        disclaimer=DISCLAIMER,
    )
