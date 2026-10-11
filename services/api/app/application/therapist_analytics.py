"""A therapist's own analytics: how their caseload is doing and how their work is going.

Everything here is a count or an average over the therapist's own records, over the last 4, 8 or
12 *completed* calendar weeks (the same windows teachers and administrators use):

* the caseload figures are averages across the students who currently have a live care link
  with this therapist *and* an active ``share_mood_with_care_team`` consent. Each student's own
  weekly mean is taken first, then the mean of those, so a heavy logger does not outweigh
  others. No student, id, name or per-student value is ever returned;
* appointments, follow-ups and the therapist's own recommendations are the therapist's own work.
  Only counts and rates: no reasons, titles, rationales or note text are read at all;
* alerts are the ones the therapist may already see in their alert list (assigned to them, or
  unassigned and so the counselling team's). Categories, excerpts and student ids are not read.

An unverified therapist has no caseload and sees all zeros, as on the dashboard.
"""

import dataclasses
import datetime as dt
import enum
import statistics
import uuid
from collections import defaultdict
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Date, Select, cast, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.errors import InvalidInput
from app.application.therapist_access import active_students, effective_verification, own_therapist
from app.application.timeutil import local_today, now_utc
from app.domain.auth.policies import Principal
from app.domain.wellness import cohort
from app.infrastructure.db import models as m
from app.infrastructure.db.audit import append_audit_event
from app.infrastructure.db.enums import (
    AlertSeverity,
    AlertStatus,
    AppointmentStatus,
    AuditOutcome,
    ConsentScope,
    FollowUpKind,
    FollowUpStatus,
    RecommendationSource,
    RecommendationStatus,
    SessionMode,
    UserRole,
)

DEFAULT_WEEKS = 8
FINAL_OUTCOMES = (
    AppointmentStatus.COMPLETED,
    AppointmentStatus.NO_SHOW,
    AppointmentStatus.CANCELLED,
)
UNACKNOWLEDGED = (AlertStatus.OPEN, AlertStatus.ESCALATED)


# ---- result types ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class CaseloadWeek:
    week_start: dt.date
    students_reporting: int
    mood_avg: float | None
    stress_avg: float | None
    sleep_hours_avg: float | None


@dataclasses.dataclass(frozen=True)
class Caseload:
    caseload_size: int
    sharing_count: int
    weekly: list[CaseloadWeek]


@dataclasses.dataclass(frozen=True)
class AppointmentWeek:
    week_start: dt.date
    scheduled: int
    completed: int
    no_show: int
    cancelled: int


@dataclasses.dataclass(frozen=True)
class Rates:
    completion: int | None
    no_show: int | None
    cancellation: int | None


@dataclasses.dataclass(frozen=True)
class Appointments:
    by_status: dict[AppointmentStatus, int]
    weekly: list[AppointmentWeek]
    rates: Rates
    by_mode: dict[SessionMode, int]


@dataclasses.dataclass(frozen=True)
class WeekCount:
    week_start: dt.date
    count: int


@dataclasses.dataclass(frozen=True)
class RecommendationProgress:
    total: int
    by_status: dict[RecommendationStatus, int]
    completion_rate: int | None
    weekly: list[WeekCount]


@dataclasses.dataclass(frozen=True)
class FollowUpProgress:
    total: int
    by_status: dict[FollowUpStatus, int]
    overdue: int
    done_on_time_rate: int | None
    by_kind: dict[FollowUpKind, int]


@dataclasses.dataclass(frozen=True)
class Interventions:
    recommendations: RecommendationProgress
    follow_ups: FollowUpProgress


@dataclasses.dataclass(frozen=True)
class Alerts:
    total: int
    by_severity: dict[AlertSeverity, int]
    by_status: dict[AlertStatus, int]
    weekly: list[WeekCount]
    acknowledged_median_minutes: float | None
    overdue_open: int
    resolved_count: int


@dataclasses.dataclass(frozen=True)
class TherapistAnalytics:
    weeks: int
    window_start: dt.date
    window_end: dt.date
    caseload: Caseload
    appointments: Appointments
    interventions: Interventions
    alerts: Alerts
    generated_at: dt.datetime


# ---- pure helpers ---------------------------------------------------------------------------


def check_weeks(weeks: int | None) -> int:
    chosen = DEFAULT_WEEKS if weeks is None else weeks
    if chosen not in cohort.ALLOWED_WEEKS:
        allowed = ", ".join(str(w) for w in cohort.ALLOWED_WEEKS)
        raise InvalidInput(f"Choose a window of {allowed} weeks.")
    return chosen


def percent(part: int, whole: int) -> int | None:
    """A whole percent, rounded half up; ``None`` when there is nothing to divide by."""
    if whole <= 0:
        return None
    return (part * 200 + whole) // (whole * 2)


def mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def median_minutes(spans: list[dt.timedelta]) -> float | None:
    if not spans:
        return None
    return round(statistics.median(s.total_seconds() / 60 for s in spans), 1)


def _week(column: Any) -> Any:
    """The Monday (UTC) of the week a timestamp falls in, as the admin figures do."""
    return cast(func.date_trunc("week", func.timezone("UTC", column)), Date)


def _utc(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time.min, tzinfo=dt.UTC)


async def _grouped(db: AsyncSession, *columns: Any, where: list[Any]) -> list[tuple[Any, ...]]:
    stmt = select(*columns, func.count()).where(*where).group_by(*columns)
    return [tuple(r) for r in (await db.execute(stmt)).all()]


def _zeros[E: enum.Enum](kind: type[E]) -> dict[E, int]:
    return {k: 0 for k in kind}


async def _distinct_students(db: AsyncSession, students: Select[Any]) -> int:
    sub = students.subquery()
    return int(await db.scalar(select(func.count(func.distinct(sub.c.student_id)))) or 0)


# ---- sections -------------------------------------------------------------------------------


async def _caseload(
    db: AsyncSession, actor: Principal, starts: list[dt.date], begin: dt.datetime, end: dt.datetime
) -> Caseload:
    linked = active_students(actor)
    size = await _distinct_students(db, linked)
    sharing: Select[Any] = linked.where(
        exists().where(
            m.Consent.user_id == m.CareTeamMember.student_id,
            m.Consent.scope == ConsentScope.SHARE_MOOD_WITH_CARE_TEAM,
            m.Consent.revoked_at.is_(None),
        )
    )
    ids = sharing.scalar_subquery()
    shared_count = await _distinct_students(db, sharing)
    last_day = starts[-1] + dt.timedelta(weeks=1)

    mood_week = _week(m.MoodEntry.logged_at)
    moods = await db.execute(
        select(m.MoodEntry.student_id, mood_week, func.avg(m.MoodEntry.mood_score))
        .where(
            m.MoodEntry.student_id.in_(ids),
            m.MoodEntry.logged_at >= begin,
            m.MoodEntry.logged_at < end,
        )
        .group_by(m.MoodEntry.student_id, mood_week)
    )
    stress_week = _week(m.StressAssessment.completed_at)
    stresses = await db.execute(
        select(
            m.StressAssessment.student_id,
            stress_week,
            func.avg(m.StressAssessment.perceived_stress_level),
        )
        .where(
            m.StressAssessment.student_id.in_(ids),
            m.StressAssessment.completed_at >= begin,
            m.StressAssessment.completed_at < end,
        )
        .group_by(m.StressAssessment.student_id, stress_week)
    )
    sleep_week = cast(func.date_trunc("week", cast(m.SleepEntry.sleep_date, Date)), Date)
    sleeps = await db.execute(
        select(m.SleepEntry.student_id, sleep_week, func.avg(m.SleepEntry.duration_minutes))
        .where(
            m.SleepEntry.student_id.in_(ids),
            m.SleepEntry.sleep_date >= starts[0],
            m.SleepEntry.sleep_date < last_day,
        )
        .group_by(m.SleepEntry.student_id, sleep_week)
    )

    # week -> metric -> one mean per student. Students are only keys here; they are dropped
    # before anything leaves this function.
    cells: dict[dt.date, dict[str, dict[uuid.UUID, float]]] = defaultdict(
        lambda: {"mood": {}, "stress": {}, "sleep": {}}
    )
    for sid, week, value in moods:
        cells[week]["mood"][sid] = float(value)
    for sid, week, value in stresses:
        cells[week]["stress"][sid] = float(value)
    for sid, week, value in sleeps:
        cells[week]["sleep"][sid] = float(value) / 60

    weekly: list[CaseloadWeek] = []
    for start in starts:
        metrics = cells.get(start, {"mood": {}, "stress": {}, "sleep": {}})
        reporting = set().union(*(metrics[k].keys() for k in metrics))
        weekly.append(
            CaseloadWeek(
                start,
                len(reporting),
                mean(list(metrics["mood"].values())),
                mean(list(metrics["stress"].values())),
                mean(list(metrics["sleep"].values())),
            )
        )
    return Caseload(size, shared_count, weekly)


async def _appointments(
    db: AsyncSession,
    actor: Principal,
    starts: list[dt.date],
    begin: dt.datetime,
    end: dt.datetime,
) -> Appointments:
    a = m.Appointment
    in_window = [
        a.therapist_id == actor.user_id,
        a.institution_id == actor.institution_id,
        a.starts_at >= begin,
        a.starts_at < end,
    ]
    by_status = _zeros(AppointmentStatus)
    for status, n in await _grouped(db, a.status, where=in_window):
        by_status[status] = n
    by_mode = _zeros(SessionMode)
    for mode, n in await _grouped(db, a.mode, where=in_window):
        by_mode[mode] = n
    week = _week(a.starts_at)
    found: dict[tuple[dt.date, AppointmentStatus], int] = {
        (w, status): n for w, status, n in await _grouped(db, week, a.status, where=in_window)
    }
    weekly: list[AppointmentWeek] = []
    for start in starts:
        counts = {s: found.get((start, s), 0) for s in AppointmentStatus}
        weekly.append(
            AppointmentWeek(
                start,
                sum(counts.values()),
                counts[AppointmentStatus.COMPLETED],
                counts[AppointmentStatus.NO_SHOW],
                counts[AppointmentStatus.CANCELLED],
            )
        )
    finished = sum(by_status[s] for s in FINAL_OUTCOMES)
    rates = Rates(
        percent(by_status[AppointmentStatus.COMPLETED], finished),
        percent(by_status[AppointmentStatus.NO_SHOW], finished),
        percent(by_status[AppointmentStatus.CANCELLED], finished),
    )
    return Appointments(by_status, weekly, rates, by_mode)


async def _recommendations(
    db: AsyncSession,
    actor: Principal,
    starts: list[dt.date],
    begin: dt.datetime,
    end: dt.datetime,
) -> RecommendationProgress:
    r = m.Recommendation
    mine = [
        r.institution_id == actor.institution_id,
        r.source == RecommendationSource.THERAPIST,
        r.authored_by == actor.user_id,
        r.created_at >= begin,
        r.created_at < end,
    ]
    by_status = _zeros(RecommendationStatus)
    for status, n in await _grouped(db, r.status, where=mine):
        by_status[status] = n
    week = _week(r.created_at)
    created = {w: n for w, n in await _grouped(db, week, where=mine)}
    total = sum(by_status.values())
    return RecommendationProgress(
        total,
        by_status,
        percent(by_status[RecommendationStatus.COMPLETED], total),
        [WeekCount(s, created.get(s, 0)) for s in starts],
    )


async def _follow_ups(
    db: AsyncSession, actor: Principal, begin: dt.datetime, end: dt.datetime, zone: ZoneInfo
) -> FollowUpProgress:
    f = m.FollowUp
    mine = [
        f.institution_id == actor.institution_id,
        f.therapist_id == actor.user_id,
        f.created_at >= begin,
        f.created_at < end,
    ]
    by_status = _zeros(FollowUpStatus)
    for status, n in await _grouped(db, f.status, where=mine):
        by_status[status] = n
    by_kind = _zeros(FollowUpKind)
    for kind, n in await _grouped(db, f.kind, where=mine):
        by_kind[kind] = n
    today = local_today(zone)
    overdue = int(
        await db.scalar(
            select(func.count())
            .select_from(f)
            .where(*mine, f.status == FollowUpStatus.OPEN, f.due_on < today)
        )
        or 0
    )
    done = (
        await db.execute(
            select(f.completed_at, f.due_on).where(*mine, f.status == FollowUpStatus.DONE)
        )
    ).all()
    on_time = sum(1 for at, due in done if at is not None and at.astimezone(zone).date() <= due)
    return FollowUpProgress(
        sum(by_status.values()), by_status, overdue, percent(on_time, len(done)), by_kind
    )


async def _alerts(
    db: AsyncSession,
    actor: Principal,
    starts: list[dt.date],
    begin: dt.datetime,
    end: dt.datetime,
    now: dt.datetime,
) -> Alerts:
    r = m.RiskAlert
    # Exactly the alerts the therapist's alert list shows (``risk_alerts.list_alerts``).
    visible = [
        r.institution_id == actor.institution_id,
        or_(r.assigned_to == actor.user_id, r.assigned_to.is_(None)),
        r.created_at >= begin,
        r.created_at < end,
    ]
    by_severity = _zeros(AlertSeverity)
    for severity, n in await _grouped(db, r.severity, where=visible):
        by_severity[severity] = n
    by_status = _zeros(AlertStatus)
    for status, n in await _grouped(db, r.status, where=visible):
        by_status[status] = n
    week = _week(r.created_at)
    raised = {w: n for w, n in await _grouped(db, week, where=visible)}
    acknowledged = (
        await db.execute(
            select(r.created_at, r.acknowledged_at).where(*visible, r.acknowledged_at.is_not(None))
        )
    ).all()
    spans = [done - created for created, done in acknowledged if done is not None]
    overdue = int(
        await db.scalar(
            select(func.count())
            .select_from(r)
            .where(*visible, r.status.in_(UNACKNOWLEDGED), r.sla_ack_due_at < now)
        )
        or 0
    )
    return Alerts(
        sum(by_status.values()),
        by_severity,
        by_status,
        [WeekCount(s, raised.get(s, 0)) for s in starts],
        median_minutes(spans),
        overdue,
        by_status[AlertStatus.RESOLVED],
    )


# ---- entry point ----------------------------------------------------------------------------


def _empty(weeks: int, starts: list[dt.date], now: dt.datetime) -> TherapistAnalytics:
    zero = [WeekCount(s, 0) for s in starts]
    return TherapistAnalytics(
        weeks,
        starts[0],
        starts[-1] + dt.timedelta(days=6),
        Caseload(0, 0, [CaseloadWeek(s, 0, None, None, None) for s in starts]),
        Appointments(
            _zeros(AppointmentStatus),
            [AppointmentWeek(s, 0, 0, 0, 0) for s in starts],
            Rates(None, None, None),
            _zeros(SessionMode),
        ),
        Interventions(
            RecommendationProgress(0, _zeros(RecommendationStatus), None, zero),
            FollowUpProgress(0, _zeros(FollowUpStatus), 0, None, _zeros(FollowUpKind)),
        ),
        Alerts(
            0,
            _zeros(AlertSeverity),
            _zeros(AlertStatus),
            zero,
            None,
            0,
            0,
        ),
        now,
    )


async def build(
    db: AsyncSession, actor: Principal, weeks: int | None, zone: ZoneInfo
) -> TherapistAnalytics:
    chosen = check_weeks(weeks)
    now = now_utc()
    starts = cohort.week_starts(now.date(), chosen)
    begin, end = _utc(starts[0]), _utc(starts[-1] + dt.timedelta(weeks=1))
    therapist = await own_therapist(db, actor)
    if effective_verification(therapist) != "verified":
        return _empty(chosen, starts, now)

    result = TherapistAnalytics(
        chosen,
        starts[0],
        starts[-1] + dt.timedelta(days=6),
        await _caseload(db, actor, starts, begin, end),
        await _appointments(db, actor, starts, begin, end),
        Interventions(
            await _recommendations(db, actor, starts, begin, end),
            await _follow_ups(db, actor, begin, end, zone),
        ),
        await _alerts(db, actor, starts, begin, end, now),
        now,
    )
    # Counts only: no student ids, no free text.
    await append_audit_event(
        db,
        institution_id=actor.institution_id,
        actor_id=actor.user_id,
        actor_role=UserRole.THERAPIST,
        action="therapist_analytics.read",
        outcome=AuditOutcome.ALLOWED,
        resource_type="analytics",
        details={
            "weeks": chosen,
            "caseload": result.caseload.caseload_size,
            "sharing": result.caseload.sharing_count,
            "appointments": sum(result.appointments.by_status.values()),
            "recommendations": result.interventions.recommendations.total,
            "follow_ups": result.interventions.follow_ups.total,
            "alerts": result.alerts.total,
        },
    )
    await db.commit()
    return result
