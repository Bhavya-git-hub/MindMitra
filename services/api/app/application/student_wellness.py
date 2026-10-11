"""A student's own wellbeing records: check-ins, mood, stress, sleep, summaries and trends.

Every function takes the authenticated ``Principal``, asks the resource policy whether this
person may use their own record, and only ever queries rows where both the student and the
institution are the caller's. Nothing here reads another person's data.
"""

import dataclasses
import datetime as dt
import logging
import uuid
from collections import defaultdict
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application import safety_workflow
from app.application.access import enforce
from app.application.errors import InvalidInput
from app.application.timeutil import day_bounds, local_today, now_utc
from app.domain.auth.policies import Principal, can_use_own_student_record
from app.domain.safety import classifier
from app.domain.safety.risk import RiskLevel, Source
from app.domain.wellness import indicators, instruments
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import GoalStatus
from app.infrastructure.db.ids import uuid7

log = logging.getLogger("mindmitra.wellness")

DAILY_STRESS_SCALE = "daily_stress_check"
MAX_LIMIT = 200
MAX_TREND_DAYS = 90
MAX_SLEEP_MINUTES = 16 * 60


def authorize_own(db: AsyncSession, actor: Principal, action: str, resource_type: str) -> None:
    """Defence in depth: the route guard already limits this to students."""
    del db
    enforce(
        can_use_own_student_record(
            actor, student_id=actor.user_id, institution_id=actor.institution_id
        ),
        action=action,
        resource_type=resource_type,
        subject_student_id=actor.user_id,
    )


# ---- check-in -------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class SleepInput:
    bedtime: dt.datetime
    wake_time: dt.datetime
    quality: int


@dataclasses.dataclass(frozen=True)
class CheckInInput:
    mood_score: int
    energy_level: int | None = None
    emotions: tuple[str, ...] = ()
    note: str | None = None
    stress_level: int | None = None
    stressors: tuple[str, ...] = ()
    sleep: SleepInput | None = None


@dataclasses.dataclass
class CheckInResult:
    mood: m.MoodEntry
    stress: m.StressAssessment | None
    sleep: m.SleepEntry | None
    support_suggested: bool
    # What the safety system found and did (MODERATE and above), see ADR 0013.
    safety: safety_workflow.SafetyOutcome | None = None


def _clean_tags(values: tuple[str, ...], limit: int, length: int) -> list[str]:
    seen: dict[str, None] = {}
    for raw in values:
        value = " ".join(raw.split()).lower()
        if not value:
            continue
        if len(value) > length:
            raise InvalidInput(f"Each label must be {length} characters or fewer.")
        seen.setdefault(value, None)
    if len(seen) > limit:
        raise InvalidInput(f"Please choose no more than {limit}.")
    return list(seen)


def _sleep_minutes(sleep: SleepInput, now: dt.datetime) -> int:
    if sleep.bedtime.tzinfo is None or sleep.wake_time.tzinfo is None:
        raise InvalidInput("Sleep times need a time zone.")
    minutes = round((sleep.wake_time - sleep.bedtime).total_seconds() / 60)
    if minutes <= 0:
        raise InvalidInput("Wake time must be after bedtime.")
    if minutes > MAX_SLEEP_MINUTES:
        raise InvalidInput("That is longer than 16 hours of sleep. Please check the times.")
    if sleep.wake_time > now + dt.timedelta(hours=1):
        raise InvalidInput("Wake time can't be in the future.")
    return minutes


async def _upsert_sleep(
    db: AsyncSession,
    actor: Principal,
    sleep: SleepInput,
    zone: ZoneInfo,
    now: dt.datetime,
) -> m.SleepEntry:
    minutes = _sleep_minutes(sleep, now)
    sleep_date = sleep.wake_time.astimezone(zone).date()
    stmt = (
        pg_insert(m.SleepEntry)
        .values(
            id=uuid7(),
            institution_id=actor.institution_id,
            student_id=actor.user_id,
            sleep_date=sleep_date,
            bedtime=sleep.bedtime,
            wake_time=sleep.wake_time,
            duration_minutes=minutes,
            quality=sleep.quality,
        )
        .on_conflict_do_update(
            constraint="uq_sleep_entries_student_date",
            set_={
                "bedtime": sleep.bedtime,
                "wake_time": sleep.wake_time,
                "duration_minutes": minutes,
                "quality": sleep.quality,
                "updated_at": now,
            },
        )
        .returning(m.SleepEntry.id)
    )
    entry_id = (await db.execute(stmt)).scalar_one()
    entry = await db.get(m.SleepEntry, entry_id, populate_existing=True)
    assert entry is not None
    return entry


def _new_stress(
    actor: Principal, level: int, stressors: list[str], now: dt.datetime
) -> m.StressAssessment:
    return m.StressAssessment(
        id=uuid7(),
        institution_id=actor.institution_id,
        student_id=actor.user_id,
        scale=DAILY_STRESS_SCALE,
        score=Decimal(level),
        max_score=Decimal(5),
        perceived_stress_level=level,
        stressors=stressors,
        completed_at=now,
    )


async def record_check_in(
    db: AsyncSession, actor: Principal, data: CheckInInput, zone: ZoneInfo
) -> CheckInResult:
    authorize_own(db, actor, "check_in.create", "mood_entry")
    now = now_utc()
    emotions = _clean_tags(data.emotions, 8, 40)
    stressors = _clean_tags(data.stressors, 8, 60)
    note = data.note.strip() if data.note and data.note.strip() else None

    mood = m.MoodEntry(
        id=uuid7(),
        institution_id=actor.institution_id,
        student_id=actor.user_id,
        mood_score=data.mood_score,
        energy_level=data.energy_level,
        emotions=emotions,
        note=note,
        logged_at=now,
    )
    db.add(mood)
    stress: m.StressAssessment | None = None
    if data.stress_level is not None:
        stress = _new_stress(actor, data.stress_level, stressors, now)
        db.add(stress)
    sleep = await _upsert_sleep(db, actor, data.sleep, zone, now) if data.sleep else None
    await db.flush()
    await db.commit()
    # The check-in is saved first, so nothing below can lose it, and set apart from the
    # session so a rollback in the safety step cannot expire what is returned.
    for saved in (mood, stress, sleep):
        if saved is not None:
            db.expunge(saved)

    found = classifier.CLASSIFIER.assess(
        text=note,
        behaviour=await _behaviour(db, actor, data.mood_score, data.stress_level, zone, now),
    )
    safety = await safety_workflow.act(db, actor, found, source=Source.CHECK_IN, now=now)
    return CheckInResult(
        mood=mood,
        stress=stress,
        sleep=sleep,
        support_suggested=found.level.at_least(RiskLevel.MODERATE),
        safety=safety,
    )


async def _behaviour(
    db: AsyncSession,
    actor: Principal,
    mood_today: int,
    stress_today: int | None,
    zone: ZoneInfo,
    now: dt.datetime,
) -> classifier.BehaviourSnapshot:
    """Today's numbers and how many of the last seven local days had a low mood."""
    low_days = 0
    try:
        first_day = local_today(zone, now) - dt.timedelta(days=classifier.SUSTAINED_WINDOW_DAYS - 1)
        rows = await db.execute(
            select(m.MoodEntry.mood_score, m.MoodEntry.logged_at).where(
                m.MoodEntry.student_id == actor.user_id,
                m.MoodEntry.institution_id == actor.institution_id,
                m.MoodEntry.logged_at
                >= now - dt.timedelta(days=classifier.SUSTAINED_WINDOW_DAYS + 1),
            )
        )
        lowest: dict[dt.date, int] = {}
        for score, at in rows.all():
            day = at.astimezone(zone).date()
            if day >= first_day:
                lowest[day] = min(score, lowest.get(day, score))
        low_days = sum(1 for v in lowest.values() if v <= classifier.SUSTAINED_LOW_MOOD_MAX)
    except Exception:  # today's numbers still count
        log.exception("could not read recent check-ins for the safety check")
        await db.rollback()
    return classifier.BehaviourSnapshot(mood_today, stress_today, low_days)


# ---- single-kind logging and history --------------------------------------------------------


async def log_stress(
    db: AsyncSession, actor: Principal, level: int, stressors: tuple[str, ...]
) -> m.StressAssessment:
    authorize_own(db, actor, "stress_entry.create", "stress_assessment")
    row = _new_stress(actor, level, _clean_tags(stressors, 8, 60), now_utc())
    db.add(row)
    await db.flush()
    await db.commit()
    return row


async def log_sleep(
    db: AsyncSession, actor: Principal, sleep: SleepInput, zone: ZoneInfo
) -> m.SleepEntry:
    authorize_own(db, actor, "sleep_entry.upsert", "sleep_entry")
    row = await _upsert_sleep(db, actor, sleep, zone, now_utc())
    await db.commit()
    return row


async def list_mood_entries(
    db: AsyncSession, actor: Principal, *, limit: int, since: dt.datetime | None = None
) -> list[m.MoodEntry]:
    authorize_own(db, actor, "mood_entry.list", "mood_entry")
    stmt = select(m.MoodEntry).where(
        m.MoodEntry.student_id == actor.user_id,
        m.MoodEntry.institution_id == actor.institution_id,
    )
    if since is not None:
        stmt = stmt.where(m.MoodEntry.logged_at >= since)
    rows = await db.scalars(
        stmt.order_by(m.MoodEntry.logged_at.desc()).limit(min(limit, MAX_LIMIT))
    )
    return list(rows)


async def list_stress_entries(
    db: AsyncSession, actor: Principal, *, limit: int, since: dt.datetime | None = None
) -> list[m.StressAssessment]:
    authorize_own(db, actor, "stress_entry.list", "stress_assessment")
    stmt = select(m.StressAssessment).where(
        m.StressAssessment.student_id == actor.user_id,
        m.StressAssessment.institution_id == actor.institution_id,
    )
    if since is not None:
        stmt = stmt.where(m.StressAssessment.completed_at >= since)
    rows = await db.scalars(
        stmt.order_by(m.StressAssessment.completed_at.desc()).limit(min(limit, MAX_LIMIT))
    )
    return list(rows)


async def list_sleep_entries(
    db: AsyncSession, actor: Principal, *, limit: int, since: dt.date | None = None
) -> list[m.SleepEntry]:
    authorize_own(db, actor, "sleep_entry.list", "sleep_entry")
    stmt = select(m.SleepEntry).where(
        m.SleepEntry.student_id == actor.user_id,
        m.SleepEntry.institution_id == actor.institution_id,
    )
    if since is not None:
        stmt = stmt.where(m.SleepEntry.sleep_date >= since)
    rows = await db.scalars(
        stmt.order_by(m.SleepEntry.sleep_date.desc()).limit(min(limit, MAX_LIMIT))
    )
    return list(rows)


# ---- assessment -----------------------------------------------------------------------------


async def submit_assessment(
    db: AsyncSession, actor: Principal, responses: dict[str, int]
) -> m.WellnessAssessment:
    authorize_own(db, actor, "wellness_assessment.create", "wellness_assessment")
    try:
        raw = instruments.score(responses)
    except instruments.InvalidResponses as exc:
        raise InvalidInput(str(exc)) from exc
    row = m.WellnessAssessment(
        id=uuid7(),
        institution_id=actor.institution_id,
        student_id=actor.user_id,
        instrument=instruments.INSTRUMENT_ID,
        instrument_version=instruments.INSTRUMENT_VERSION,
        score=Decimal(raw),
        max_score=Decimal(instruments.MAX_SCORE),
        responses=dict(responses),
        completed_at=now_utc(),
    )
    db.add(row)
    await db.flush()
    await db.commit()
    return row


async def list_assessments(
    db: AsyncSession, actor: Principal, limit: int
) -> list[m.WellnessAssessment]:
    authorize_own(db, actor, "wellness_assessment.list", "wellness_assessment")
    rows = await db.scalars(
        select(m.WellnessAssessment)
        .where(
            m.WellnessAssessment.student_id == actor.user_id,
            m.WellnessAssessment.institution_id == actor.institution_id,
        )
        .order_by(m.WellnessAssessment.completed_at.desc())
        .limit(min(limit, MAX_LIMIT))
    )
    return list(rows)


# ---- summary and trends ---------------------------------------------------------------------


@dataclasses.dataclass
class DailyPoint:
    day: dt.date
    mood: float | None = None
    energy: float | None = None
    stress: float | None = None
    sleep_minutes: int | None = None
    sleep_quality: int | None = None


async def daily_series(
    db: AsyncSession, actor: Principal, days: int, zone: ZoneInfo
) -> list[DailyPoint]:
    """One point per local calendar day, oldest first, ending today (None where nothing logged)."""
    authorize_own(db, actor, "wellness_trend.read", "wellness_trend")
    return await series_for_student(db, actor.user_id, actor.institution_id, days, zone)


async def series_for_student(
    db: AsyncSession,
    student_id: uuid.UUID,
    institution_id: uuid.UUID,
    days: int,
    zone: ZoneInfo,
) -> list[DailyPoint]:
    """The series itself. Callers MUST have authorised access to this student first (the
    student for themselves, or a therapist with a care link and the student's consent)."""
    if not 1 <= days <= MAX_TREND_DAYS:
        raise InvalidInput(f"days must be between 1 and {MAX_TREND_DAYS}.")
    today = local_today(zone)
    first = today - dt.timedelta(days=days - 1)
    start, _ = day_bounds(first, zone)

    moods = await db.execute(
        select(m.MoodEntry.logged_at, m.MoodEntry.mood_score, m.MoodEntry.energy_level).where(
            m.MoodEntry.student_id == student_id,
            m.MoodEntry.institution_id == institution_id,
            m.MoodEntry.logged_at >= start,
        )
    )
    stresses = await db.execute(
        select(m.StressAssessment.completed_at, m.StressAssessment.perceived_stress_level).where(
            m.StressAssessment.student_id == student_id,
            m.StressAssessment.institution_id == institution_id,
            m.StressAssessment.completed_at >= start,
        )
    )
    sleeps = await db.execute(
        select(m.SleepEntry.sleep_date, m.SleepEntry.duration_minutes, m.SleepEntry.quality).where(
            m.SleepEntry.student_id == student_id,
            m.SleepEntry.institution_id == institution_id,
            m.SleepEntry.sleep_date >= first,
        )
    )
    mood_by: dict[dt.date, list[int]] = defaultdict(list)
    energy_by: dict[dt.date, list[int]] = defaultdict(list)
    for at, score, energy in moods.all():
        day = at.astimezone(zone).date()
        mood_by[day].append(score)
        if energy is not None:
            energy_by[day].append(energy)
    stress_by: dict[dt.date, list[int]] = defaultdict(list)
    for at, level in stresses.all():
        stress_by[at.astimezone(zone).date()].append(level)
    sleep_by = {d: (mins, q) for d, mins, q in sleeps.all()}

    out: list[DailyPoint] = []
    for offset in range(days):
        day = first + dt.timedelta(days=offset)
        sleep = sleep_by.get(day)
        out.append(
            DailyPoint(
                day=day,
                mood=indicators.average(mood_by.get(day, [])),
                energy=indicators.average(energy_by.get(day, [])),
                stress=indicators.average(stress_by.get(day, [])),
                sleep_minutes=sleep[0] if sleep else None,
                sleep_quality=sleep[1] if sleep else None,
            )
        )
    return out


@dataclasses.dataclass
class Summary:
    today: dt.date
    checked_in_today: bool
    mood_today: float | None
    mood_today_emotions: list[str]
    stress_today: float | None
    sleep_last_night: m.SleepEntry | None
    avg_mood_7d: float | None
    avg_stress_7d: float | None
    avg_sleep_minutes_7d: float | None
    mood_direction: str | None
    stress_direction: str | None
    sleep_direction: str | None
    streak_days: int
    days_since_check_in: int | None
    check_ins_last_7d: int
    latest_assessment: m.WellnessAssessment | None
    active_goals: int


def _mean(values: list[float | int]) -> float | None:
    return indicators.average([float(v) for v in values])


async def summary(db: AsyncSession, actor: Principal, zone: ZoneInfo) -> Summary:
    authorize_own(db, actor, "wellness_summary.read", "wellness_summary")
    today = local_today(zone)
    series = await daily_series(db, actor, 14, zone)  # oldest first; last 7 = this week
    this_week, last_week = series[-7:], series[:7]

    def avg(points: list[DailyPoint], attr: str) -> float | None:
        return _mean([v for p in points if (v := getattr(p, attr)) is not None])

    check_in_days = {p.day for p in series if p.mood is not None}
    today_point = series[-1]

    sleep_row = await db.scalar(
        select(m.SleepEntry)
        .where(
            m.SleepEntry.student_id == actor.user_id,
            m.SleepEntry.institution_id == actor.institution_id,
            m.SleepEntry.sleep_date >= today - dt.timedelta(days=1),
        )
        .order_by(m.SleepEntry.sleep_date.desc())
        .limit(1)
    )
    start, end = day_bounds(today, zone)
    latest_today = await db.scalar(
        select(m.MoodEntry)
        .where(
            m.MoodEntry.student_id == actor.user_id,
            m.MoodEntry.institution_id == actor.institution_id,
            m.MoodEntry.logged_at >= start,
            m.MoodEntry.logged_at < end,
        )
        .order_by(m.MoodEntry.logged_at.desc())
        .limit(1)
    )
    last_checkin_at = await db.scalar(
        select(m.MoodEntry.logged_at)
        .where(
            m.MoodEntry.student_id == actor.user_id,
            m.MoodEntry.institution_id == actor.institution_id,
        )
        .order_by(m.MoodEntry.logged_at.desc())
        .limit(1)
    )
    assessment = await db.scalar(
        select(m.WellnessAssessment)
        .where(
            m.WellnessAssessment.student_id == actor.user_id,
            m.WellnessAssessment.institution_id == actor.institution_id,
        )
        .order_by(m.WellnessAssessment.completed_at.desc())
        .limit(1)
    )
    goal_count = await _count_active_goals(db, actor)

    days_since = (
        None if last_checkin_at is None else (today - last_checkin_at.astimezone(zone).date()).days
    )
    return Summary(
        today=today,
        checked_in_today=today in check_in_days,
        mood_today=today_point.mood,
        mood_today_emotions=list(latest_today.emotions) if latest_today else [],
        stress_today=today_point.stress,
        sleep_last_night=sleep_row,
        avg_mood_7d=avg(this_week, "mood"),
        avg_stress_7d=avg(this_week, "stress"),
        avg_sleep_minutes_7d=avg(this_week, "sleep_minutes"),
        mood_direction=indicators.direction(
            avg(this_week, "mood"), avg(last_week, "mood"), threshold=0.3
        ),
        stress_direction=indicators.direction(
            avg(this_week, "stress"), avg(last_week, "stress"), threshold=0.3
        ),
        sleep_direction=indicators.direction(
            avg(this_week, "sleep_minutes"), avg(last_week, "sleep_minutes"), threshold=20
        ),
        streak_days=indicators.streak_days(check_in_days, today),
        days_since_check_in=days_since,
        check_ins_last_7d=sum(1 for p in this_week if p.mood is not None),
        latest_assessment=assessment,
        active_goals=goal_count,
    )


async def _count_active_goals(db: AsyncSession, actor: Principal) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(m.WellnessGoal)
            .where(
                m.WellnessGoal.student_id == actor.user_id,
                m.WellnessGoal.institution_id == actor.institution_id,
                m.WellnessGoal.status == GoalStatus.ACTIVE,
            )
        )
        or 0
    )
