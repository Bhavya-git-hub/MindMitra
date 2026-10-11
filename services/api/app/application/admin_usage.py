"""Administrator service analytics: usage, counselling utilisation, intervention engagement.

Everything here is a count or a share over many people. Nothing names a student, and nothing
reads what anyone wrote, said or was recommended:

* **usage**: how often the platform is used each completed week. Message counts are rows
  counted, never opened (no body is selected, so nothing is decrypted). Every count from 1 to 4
  is shown as "fewer than 5" (``None``), zero stays zero.
* **utilisation**: how much of the hours therapists offered were booked, whole-number percent
  rounded to the nearest 5. A cell with 1 to 4 booked slots hides its booked hours and percent
  for the same reason as any other small count. No-show and cancellation shares follow
  ``cohort.share`` on appointment counts.
* **engagement**: what happened to the suggestions made in the window, by where they came from
  and by problem area. A group is shown only when at least ``MIN_GROUP`` *different* students
  contribute to it, whatever the number of suggestions; otherwise every count in it is ``None``
  and ``suppressed`` is true. Student ids are used inside the queries to count distinct people
  and are never returned.
"""

import dataclasses
import datetime as dt
import math
from typing import Any

from sqlalchemy import Select, distinct, func, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.admin_common import audit
from app.application.admin_insights import _bounds, _week, _weekly, check_weeks, small_safe
from app.application.timeutil import now_utc
from app.domain.auth.policies import Principal
from app.domain.wellness import cohort
from app.domain.wellness.recommender.catalog import AREAS
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import (
    AIMessageRole,
    AppointmentStatus,
    AuditOutcome,
    FeedbackRating,
    RecommendationSource,
    RecommendationStatus,
    SessionMode,
)

OTHER_AREA = "other"
SIGN_IN_ACTION = "auth.login"
TOP_INTERVENTIONS = 5
PERCENT_STEP = 5
DISCLAIMER = (
    "These figures are counts and averages over many people. Numbers from 1 to 4 are shown as "
    "“fewer than 5”, groups with fewer than 5 people are not shown, and nothing here describes "
    "or identifies an individual."
)


# ---- results ---------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class UsageWeek:
    week_start: dt.date
    check_ins: int | None
    active_students: int | None
    companion_messages: int | None
    therapist_messages: int | None
    sign_ins: int | None


@dataclasses.dataclass(frozen=True)
class UsageTotals:
    check_ins: int | None
    active_students: int | None
    companion_messages: int | None
    therapist_messages: int | None
    sign_ins: int | None


@dataclasses.dataclass(frozen=True)
class Usage:
    weekly: list[UsageWeek]
    totals: UsageTotals


@dataclasses.dataclass(frozen=True)
class UtilisationWeek:
    week_start: dt.date
    capacity_hours: float
    booked_hours: float | None
    utilisation_percent: int | None


@dataclasses.dataclass(frozen=True)
class UtilisationFigures:
    capacity_hours: float
    booked_hours: float | None
    utilisation_percent: int | None
    no_show_share: cohort.Share
    cancellation_share: cohort.Share


@dataclasses.dataclass(frozen=True)
class ModeUtilisation:
    mode: SessionMode
    figures: UtilisationFigures


@dataclasses.dataclass(frozen=True)
class Utilisation:
    overall: UtilisationFigures
    weekly: list[UtilisationWeek]
    by_mode: list[ModeUtilisation]


@dataclasses.dataclass(frozen=True)
class EngagementGroup:
    key: str
    suppressed: bool
    suggestions: int | None
    viewed: int | None
    completed: int | None
    dismissed: int | None
    helpful: int | None
    not_helpful: int | None


@dataclasses.dataclass(frozen=True)
class TopIntervention:
    intervention_key: str
    students: int  # distinct students, rounded down to the nearest 5


@dataclasses.dataclass(frozen=True)
class Engagement:
    by_source: list[EngagementGroup]
    by_problem_area: list[EngagementGroup]
    completion_share: cohort.Share
    helpful_share: cohort.Share
    top_interventions: list[TopIntervention]


@dataclasses.dataclass(frozen=True)
class ServiceAnalytics:
    weeks: int
    window_start: dt.date
    window_end: dt.date  # the last day included (a Sunday)
    usage: Usage
    utilisation: Utilisation
    engagement: Engagement
    generated_at: dt.datetime


# ---- usage -----------------------------------------------------------------------------------


def _active_union(inst: Any, begin: dt.datetime, end: dt.datetime) -> Any:
    """One (week, student) row per entry of any kind in the window, as a subquery."""

    def part(student: Any, institution: Any, when: Any) -> Select[Any]:
        return select(_week(when).label("week"), student.label("student")).where(
            institution == inst, when >= begin, when < end
        )

    return union_all(
        part(m.MoodEntry.student_id, m.MoodEntry.institution_id, m.MoodEntry.logged_at),
        part(
            m.StressAssessment.student_id,
            m.StressAssessment.institution_id,
            m.StressAssessment.completed_at,
        ),
        part(m.SleepEntry.student_id, m.SleepEntry.institution_id, m.SleepEntry.wake_time),
    ).subquery()


async def _usage(
    db: AsyncSession, inst: Any, starts: list[dt.date], begin: dt.datetime, end: dt.datetime
) -> Usage:
    moods = [m.MoodEntry.institution_id == inst]
    comm = [m.Message.institution_id == inst]
    # Only the role and the timestamp of a companion message are used, never its content.
    companion = [
        m.AIMessage.role == AIMessageRole.USER,
        m.AIMessage.conversation_id.in_(
            select(m.AIConversation.id).where(m.AIConversation.institution_id == inst)
        ),
    ]
    sign_in = [
        m.AuditLog.institution_id == inst,
        m.AuditLog.action == SIGN_IN_ACTION,
        m.AuditLog.outcome == AuditOutcome.ALLOWED,
    ]
    check_ins = await _weekly(db, m.MoodEntry.logged_at, moods, starts, begin, end)
    messages = await _weekly(db, m.Message.created_at, comm, starts, begin, end)
    chats = await _weekly(db, m.AIMessage.created_at, companion, starts, begin, end)
    sign_ins = await _weekly(db, m.AuditLog.occurred_at, sign_in, starts, begin, end)

    union = _active_union(inst, begin, end)
    per_week = {
        week: n
        for week, n in (
            await db.execute(
                select(union.c.week, func.count(distinct(union.c.student))).group_by(union.c.week)
            )
        ).all()
    }
    active_total = await db.scalar(select(func.count(distinct(union.c.student)))) or 0

    async def total(column: Any, filters: list[Any]) -> int | None:
        n = await db.scalar(select(func.count()).where(column >= begin, column < end, *filters))
        return small_safe(n or 0)

    weekly = [
        UsageWeek(
            week_start=c.week_start,
            check_ins=c.count,
            active_students=small_safe(per_week.get(c.week_start, 0)),
            companion_messages=chats[i].count,
            therapist_messages=messages[i].count,
            sign_ins=sign_ins[i].count,
        )
        for i, c in enumerate(check_ins)
    ]
    totals = UsageTotals(
        check_ins=await total(m.MoodEntry.logged_at, moods),
        active_students=small_safe(active_total),
        companion_messages=await total(m.AIMessage.created_at, companion),
        therapist_messages=await total(m.Message.created_at, comm),
        sign_ins=await total(m.AuditLog.occurred_at, sign_in),
    )
    return Usage(weekly, totals)


# ---- counselling utilisation -----------------------------------------------------------------


def percent_to_5(part: float, whole: float) -> int | None:
    """A whole-number percentage rounded (half up) to the nearest 5; ``None`` when no whole."""
    if whole <= 0:
        return None
    return int(math.floor(part * 100 / whole / PERCENT_STEP + 0.5)) * PERCENT_STEP


def _hours(seconds: float) -> float:
    return round(seconds / 3600, 1)


@dataclasses.dataclass
class _Slots:
    """Slot totals for one cell (a week, a mode, or everything)."""

    slots: int = 0
    seconds: float = 0.0
    booked_slots: int = 0
    booked_seconds: float = 0.0

    def add(self, other: "_Slots") -> None:
        self.slots += other.slots
        self.seconds += other.seconds
        self.booked_slots += other.booked_slots
        self.booked_seconds += other.booked_seconds

    def booked_hours(self) -> float | None:
        return None if small_safe(self.booked_slots) is None else _hours(self.booked_seconds)

    def percent(self) -> int | None:
        if small_safe(self.booked_slots) is None:
            return None
        return percent_to_5(self.booked_seconds, self.seconds)


async def _slot_cells(
    db: AsyncSession, inst: Any, begin: dt.datetime, end: dt.datetime
) -> dict[tuple[dt.date, SessionMode], _Slots]:
    slot = m.TherapistAvailability
    seconds = func.extract("epoch", slot.ends_at - slot.starts_at)
    live = (
        select(m.Appointment.availability_id)
        .where(
            m.Appointment.institution_id == inst,
            m.Appointment.availability_id.is_not(None),
            m.Appointment.status != AppointmentStatus.CANCELLED,
        )
        .distinct()
    )
    booked = slot.id.in_(live)
    week = _week(slot.starts_at)
    rows = await db.execute(
        select(
            week,
            slot.mode,
            func.count(),
            func.coalesce(func.sum(seconds), 0),
            func.count().filter(booked),
            func.coalesce(func.sum(seconds).filter(booked), 0),
        )
        .where(slot.institution_id == inst, slot.starts_at >= begin, slot.starts_at < end)
        .group_by(week, slot.mode)
    )
    return {
        (wk, mode): _Slots(n, float(secs), booked_n, float(booked_secs))
        for wk, mode, n, secs, booked_n, booked_secs in rows.all()
    }


async def _appointment_shares(
    db: AsyncSession, inst: Any, begin: dt.datetime, end: dt.datetime
) -> dict[SessionMode | None, tuple[cohort.Share, cohort.Share]]:
    """No-show and cancellation shares for everything (key ``None``) and for each mode."""
    rows = await db.execute(
        select(m.Appointment.mode, m.Appointment.status, func.count())
        .where(
            m.Appointment.institution_id == inst,
            m.Appointment.starts_at >= begin,
            m.Appointment.starts_at < end,
        )
        .group_by(m.Appointment.mode, m.Appointment.status)
    )
    tally: dict[SessionMode | None, dict[AppointmentStatus, int]] = {None: {}}
    tally.update({mode: {} for mode in SessionMode})
    for mode, status, n in rows.all():
        for key in (None, mode):
            tally[key][status] = tally[key].get(status, 0) + n

    def shares(by: dict[AppointmentStatus, int]) -> tuple[cohort.Share, cohort.Share]:
        no_show = by.get(AppointmentStatus.NO_SHOW, 0)
        held = no_show + by.get(AppointmentStatus.COMPLETED, 0)
        return (
            cohort.share(no_show, held),
            cohort.share(by.get(AppointmentStatus.CANCELLED, 0), sum(by.values())),
        )

    return {key: shares(by) for key, by in tally.items()}


async def _utilisation(
    db: AsyncSession, inst: Any, starts: list[dt.date], begin: dt.datetime, end: dt.datetime
) -> Utilisation:
    cells = await _slot_cells(db, inst, begin, end)
    shares = await _appointment_shares(db, inst, begin, end)

    def figures(total: _Slots, key: SessionMode | None) -> UtilisationFigures:
        no_show, cancelled = shares[key]
        return UtilisationFigures(
            _hours(total.seconds), total.booked_hours(), total.percent(), no_show, cancelled
        )

    weekly: list[UtilisationWeek] = []
    for start in starts:
        week = _Slots()
        for mode in SessionMode:
            week.add(cells.get((start, mode), _Slots()))
        weekly.append(
            UtilisationWeek(start, _hours(week.seconds), week.booked_hours(), week.percent())
        )

    overall = _Slots()
    by_mode: list[ModeUtilisation] = []
    for mode in SessionMode:
        mine = _Slots()
        for start in starts:
            mine.add(cells.get((start, mode), _Slots()))
        overall.add(mine)
        by_mode.append(ModeUtilisation(mode, figures(mine, mode)))
    return Utilisation(figures(overall, None), weekly, by_mode)


# ---- intervention engagement -----------------------------------------------------------------


def _group(key: str, row: Any) -> EngagementGroup:
    """One group from its aggregate row, or a suppressed one when too few students are in it."""
    if row is None or row.students < cohort.MIN_GROUP:
        return EngagementGroup(key, True, None, None, None, None, None, None)
    return EngagementGroup(
        key,
        False,
        small_safe(row.suggestions),
        small_safe(row.viewed),
        small_safe(row.completed),
        small_safe(row.dismissed),
        small_safe(row.helpful),
        small_safe(row.not_helpful),
    )


async def _grouped(
    db: AsyncSession, inst: Any, begin: dt.datetime, end: dt.datetime, column: Any
) -> dict[str, Any]:
    rec = m.Recommendation
    rows = await db.execute(
        select(
            column.label("key"),
            func.count(distinct(rec.student_id)).label("students"),
            func.count().label("suggestions"),
            func.count().filter(rec.status == RecommendationStatus.VIEWED).label("viewed"),
            func.count().filter(rec.status == RecommendationStatus.COMPLETED).label("completed"),
            func.count().filter(rec.status == RecommendationStatus.DISMISSED).label("dismissed"),
            func.count()
            .filter(m.RecommendationFeedback.rating == FeedbackRating.HELPFUL)
            .label("helpful"),
            func.count()
            .filter(m.RecommendationFeedback.rating == FeedbackRating.NOT_HELPFUL)
            .label("not_helpful"),
        )
        .select_from(rec)
        .outerjoin(m.RecommendationFeedback, m.RecommendationFeedback.recommendation_id == rec.id)
        .where(rec.institution_id == inst, rec.created_at >= begin, rec.created_at < end)
        .group_by(column)
    )
    return {str(r.key): r for r in rows.all()}


async def _engagement(
    db: AsyncSession, inst: Any, begin: dt.datetime, end: dt.datetime
) -> Engagement:
    rec = m.Recommendation
    area = func.coalesce(rec.problem_area, OTHER_AREA)
    sources = await _grouped(db, inst, begin, end, rec.source)
    areas = await _grouped(db, inst, begin, end, area)

    by_source = [_group(s.value, sources.get(s.value)) for s in RecommendationSource]
    known = (*AREAS, OTHER_AREA)
    by_area = [_group(a, areas.get(a)) for a in known]

    people = (
        await db.execute(
            select(
                func.count(distinct(rec.student_id)),
                func.count(distinct(rec.student_id)).filter(
                    rec.status == RecommendationStatus.COMPLETED
                ),
                func.count(distinct(m.RecommendationFeedback.student_id)),
                func.count(distinct(m.RecommendationFeedback.student_id)).filter(
                    m.RecommendationFeedback.rating == FeedbackRating.HELPFUL
                ),
            )
            .select_from(rec)
            .outerjoin(
                m.RecommendationFeedback, m.RecommendationFeedback.recommendation_id == rec.id
            )
            .where(rec.institution_id == inst, rec.created_at >= begin, rec.created_at < end)
        )
    ).one()
    suggested, completed, rated, found_helpful = people

    students = func.count(distinct(rec.student_id))
    top = (
        await db.execute(
            select(rec.intervention_key, students)
            .where(
                rec.institution_id == inst,
                rec.created_at >= begin,
                rec.created_at < end,
                rec.intervention_key.is_not(None),
            )
            .group_by(rec.intervention_key)
            .having(students >= cohort.MIN_GROUP)
            .order_by(students.desc(), rec.intervention_key)
            .limit(TOP_INTERVENTIONS)
        )
    ).all()
    return Engagement(
        by_source=by_source,
        by_problem_area=by_area,
        completion_share=cohort.share(completed, suggested),
        helpful_share=cohort.share(found_helpful, rated),
        top_interventions=[TopIntervention(key, n // 5 * 5) for key, n in top if key is not None],
    )


# ---- entry point -----------------------------------------------------------------------------


async def service_analytics(
    db: AsyncSession, actor: Principal, weeks: int | None
) -> ServiceAnalytics:
    chosen = check_weeks(weeks)
    inst = actor.institution_id
    starts, begin, end = _bounds(chosen)
    usage = await _usage(db, inst, starts, begin, end)
    utilisation = await _utilisation(db, inst, starts, begin, end)
    engagement = await _engagement(db, inst, begin, end)
    groups = [*engagement.by_source, *engagement.by_problem_area]
    await audit(
        db,
        actor,
        "service_analytics.read",
        resource_type="analytics",
        weeks=chosen,
        groups=len(groups),
        suppressed_groups=sum(1 for g in groups if g.suppressed),
    )
    await db.commit()
    return ServiceAnalytics(
        weeks=chosen,
        window_start=starts[0],
        window_end=starts[-1] + dt.timedelta(days=6),
        usage=usage,
        utilisation=utilisation,
        engagement=engagement,
        generated_at=now_utc(),
    )
