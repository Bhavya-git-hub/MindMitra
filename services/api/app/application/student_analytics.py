"""A student's own analytics: weekly self-reported figures, wellbeing checks and goal progress.

Everything here is derived from the caller's own entries, in the caller's own local weeks
(Monday to Sunday). It reuses the daily series and the assessment history rather than querying
the same rows again, and it never looks at anyone else's records. The figures describe what the
student reported; they are not a clinical measure.
"""

import dataclasses
import datetime as dt
from collections import defaultdict
from collections.abc import Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application import student_wellness
from app.application.errors import InvalidInput
from app.application.student_wellness import DailyPoint, authorize_own
from app.application.timeutil import local_today
from app.domain.auth.policies import Principal
from app.domain.wellness import indicators
from app.domain.wellness.cohort import monday_of
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import GoalCategory, GoalStatus

MIN_WEEKS = 4
MAX_WEEKS = 12
DEFAULT_WEEKS = 8
WELLBEING_CHECKS_SHOWN = 12


@dataclasses.dataclass(frozen=True)
class WeekFigures:
    week_start: dt.date  # the Monday, in the student's own time zone
    wellness_index: int | None
    mood_avg: float | None
    stress_avg: float | None
    sleep_quality_avg: float | None
    sleep_hours_avg: float | None
    days_reported: int
    partial: bool  # the current week is not over yet


@dataclasses.dataclass(frozen=True)
class WeekCount:
    week_start: dt.date
    completed: int


@dataclasses.dataclass(frozen=True)
class CategoryProgress:
    category: GoalCategory
    active: int
    completed: int
    average_progress_percent: float | None


@dataclasses.dataclass(frozen=True)
class GoalFigures:
    active: int
    completed: int
    other: int  # paused or set aside
    average_progress_percent: float | None  # active goals that have a target
    by_category: list[CategoryProgress]
    completed_by_week: list[WeekCount]


@dataclasses.dataclass(frozen=True)
class StudentAnalytics:
    weeks: list[WeekFigures]
    wellbeing_checks: list[m.WellnessAssessment]  # oldest first
    goals: GoalFigures


def check_weeks(weeks: int) -> int:
    if not MIN_WEEKS <= weeks <= MAX_WEEKS:
        raise InvalidInput(f"weeks must be between {MIN_WEEKS} and {MAX_WEEKS}.")
    return weeks


def week_starts(today: dt.date, weeks: int) -> list[dt.date]:
    """The Mondays of the last ``weeks`` weeks including the current one, oldest first."""
    this_week = monday_of(today)
    return [this_week - dt.timedelta(weeks=n) for n in range(weeks - 1, -1, -1)]


def _reported(point: DailyPoint) -> bool:
    return any(
        v is not None
        for v in (point.mood, point.energy, point.stress, point.sleep_minutes, point.sleep_quality)
    )


def weekly_figures(series: Sequence[DailyPoint], starts: Sequence[dt.date]) -> list[WeekFigures]:
    """Average each local week's daily points. A week with nothing reported keeps its place
    with empty figures, so a gap shows as a gap."""
    by_week: dict[dt.date, list[DailyPoint]] = defaultdict(list)
    for point in series:
        by_week[monday_of(point.day)].append(point)
    current = monday_of(series[-1].day) if series else None

    out: list[WeekFigures] = []
    for start in starts:
        points = by_week.get(start, [])
        mood = indicators.average([p.mood for p in points if p.mood is not None])
        stress = indicators.average([p.stress for p in points if p.stress is not None])
        quality = indicators.average(
            [float(p.sleep_quality) for p in points if p.sleep_quality is not None]
        )
        hours = indicators.average(
            [p.sleep_minutes / 60 for p in points if p.sleep_minutes is not None]
        )
        out.append(
            WeekFigures(
                week_start=start,
                wellness_index=indicators.wellness_index(mood, stress, quality),
                mood_avg=mood,
                stress_avg=stress,
                sleep_quality_avg=quality,
                sleep_hours_avg=hours,
                days_reported=sum(1 for p in points if _reported(p)),
                partial=start == current,
            )
        )
    return out


def _mean_percent(values: Sequence[int]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def goal_figures(
    goals: Sequence[m.WellnessGoal], starts: Sequence[dt.date], zone: ZoneInfo
) -> GoalFigures:
    """Counts, progress and completions per local week. Goals keep only their current value,
    so progress is a snapshot of today, not a history."""
    progress: dict[GoalCategory, list[int]] = defaultdict(list)
    active: dict[GoalCategory, int] = defaultdict(int)
    completed: dict[GoalCategory, int] = defaultdict(int)
    all_progress: list[int] = []
    other = 0
    done_by_week: dict[dt.date, int] = defaultdict(int)

    for goal in goals:
        if goal.status is GoalStatus.ACTIVE:
            active[goal.category] += 1
            pct = indicators.goal_progress_percent(
                float(goal.current_value),
                None if goal.target_value is None else float(goal.target_value),
            )
            if pct is not None:
                progress[goal.category].append(pct)
                all_progress.append(pct)
        elif goal.status is GoalStatus.COMPLETED:
            completed[goal.category] += 1
            if goal.completed_at is not None:
                done_by_week[monday_of(goal.completed_at.astimezone(zone).date())] += 1
        else:
            other += 1

    categories = sorted(set(active) | set(completed), key=lambda c: c.value)
    return GoalFigures(
        active=sum(active.values()),
        completed=sum(completed.values()),
        other=other,
        average_progress_percent=_mean_percent(all_progress),
        by_category=[
            CategoryProgress(
                category=c,
                active=active[c],
                completed=completed[c],
                average_progress_percent=_mean_percent(progress[c]),
            )
            for c in categories
        ],
        completed_by_week=[WeekCount(start, done_by_week.get(start, 0)) for start in starts],
    )


async def student_analytics(
    db: AsyncSession, actor: Principal, weeks: int, zone: ZoneInfo
) -> StudentAnalytics:
    authorize_own(db, actor, "wellness_analytics.read", "wellness_analytics")
    check_weeks(weeks)
    today = local_today(zone)
    starts = week_starts(today, weeks)
    days = (today - starts[0]).days + 1
    series = await student_wellness.daily_series(db, actor, days, zone)

    checks = await student_wellness.list_assessments(db, actor, WELLBEING_CHECKS_SHOWN)
    rows = await db.scalars(
        select(m.WellnessGoal).where(
            m.WellnessGoal.student_id == actor.user_id,
            m.WellnessGoal.institution_id == actor.institution_id,
        )
    )
    return StudentAnalytics(
        weeks=weekly_figures(series, starts),
        wellbeing_checks=list(reversed(checks)),
        goals=goal_figures(list(rows), starts, zone),
    )
