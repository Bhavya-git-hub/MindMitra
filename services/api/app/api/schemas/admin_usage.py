"""Response body for the administrator service analytics (counts and shares only).

No field carries a student, a therapist, a message, a recommendation title or any free text.
A ``null`` count means "fewer than 5"; a suppressed engagement group has only ``null`` counts.
"""

import dataclasses
import datetime as dt

from pydantic import BaseModel, Field

from app.application import admin_usage as u
from app.domain.wellness import cohort

Count = int | None


class ShareOut(BaseModel):
    """``shown``: ``percent`` (rounded to 5). ``few``/``most``/``hidden``: no number at all."""

    state: str
    percent: int | None


class UsageWeekOut(BaseModel):
    week_start: dt.date
    check_ins: Count = Field(description="null means fewer than 5")
    active_students: Count
    companion_messages: Count
    therapist_messages: Count
    sign_ins: Count


class UsageTotalsOut(BaseModel):
    check_ins: Count
    active_students: Count
    companion_messages: Count
    therapist_messages: Count
    sign_ins: Count


class UsageOut(BaseModel):
    weekly: list[UsageWeekOut]
    totals: UsageTotalsOut


class UtilisationWeekOut(BaseModel):
    week_start: dt.date
    capacity_hours: float
    booked_hours: float | None = Field(description="null means fewer than 5 booked slots")
    utilisation_percent: int | None = Field(description="rounded to 5; null: no capacity or <5")


class UtilisationFiguresOut(BaseModel):
    capacity_hours: float
    booked_hours: float | None
    utilisation_percent: int | None
    no_show_share: ShareOut
    cancellation_share: ShareOut


class ModeUtilisationOut(UtilisationFiguresOut):
    mode: str


class UtilisationOut(BaseModel):
    overall: UtilisationFiguresOut
    weekly: list[UtilisationWeekOut]
    by_mode: list[ModeUtilisationOut]


class EngagementGroupOut(BaseModel):
    key: str
    suppressed: bool = Field(description="true: fewer than 5 different students; counts are null")
    suggestions: Count
    viewed: Count
    completed: Count
    dismissed: Count
    helpful: Count
    not_helpful: Count


class TopInterventionOut(BaseModel):
    intervention_key: str
    students: int = Field(description="different students, rounded down to the nearest 5")


class EngagementOut(BaseModel):
    by_source: list[EngagementGroupOut]
    by_problem_area: list[EngagementGroupOut]
    completion_share: ShareOut
    helpful_share: ShareOut
    top_interventions: list[TopInterventionOut]


class ServiceAnalyticsOut(BaseModel):
    window_weeks: int
    window_start: dt.date
    window_end: dt.date
    usage: UsageOut
    utilisation: UtilisationOut
    engagement: EngagementOut
    disclaimer: str
    generated_at: dt.datetime


def _share(s: cohort.Share) -> ShareOut:
    return ShareOut(state=s.state, percent=s.percent)


def _figures(f: u.UtilisationFigures) -> UtilisationFiguresOut:
    return UtilisationFiguresOut(
        capacity_hours=f.capacity_hours,
        booked_hours=f.booked_hours,
        utilisation_percent=f.utilisation_percent,
        no_show_share=_share(f.no_show_share),
        cancellation_share=_share(f.cancellation_share),
    )


def _group(g: u.EngagementGroup) -> EngagementGroupOut:
    return EngagementGroupOut(**dataclasses.asdict(g))


def service_analytics_out(a: u.ServiceAnalytics) -> ServiceAnalyticsOut:
    use, util, eng = a.usage, a.utilisation, a.engagement
    return ServiceAnalyticsOut(
        window_weeks=a.weeks,
        window_start=a.window_start,
        window_end=a.window_end,
        usage=UsageOut(
            weekly=[UsageWeekOut(**dataclasses.asdict(w)) for w in use.weekly],
            totals=UsageTotalsOut(**dataclasses.asdict(use.totals)),
        ),
        utilisation=UtilisationOut(
            overall=_figures(util.overall),
            weekly=[UtilisationWeekOut(**dataclasses.asdict(w)) for w in util.weekly],
            by_mode=[
                ModeUtilisationOut(mode=x.mode.value, **_figures(x.figures).model_dump())
                for x in util.by_mode
            ],
        ),
        engagement=EngagementOut(
            by_source=[_group(g) for g in eng.by_source],
            by_problem_area=[_group(g) for g in eng.by_problem_area],
            completion_share=_share(eng.completion_share),
            helpful_share=_share(eng.helpful_share),
            top_interventions=[
                TopInterventionOut(intervention_key=t.intervention_key, students=t.students)
                for t in eng.top_interventions
            ],
        ),
        disclaimer=u.DISCLAIMER,
        generated_at=a.generated_at,
    )
