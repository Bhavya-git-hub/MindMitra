"""The numbers the engine reasons about, computed from a student's own recent records.

Everything here is a plain average or share over the last 14 days (``RECENT_DAYS``) of what the
student chose to log. Missing answers are left out, not guessed: a signal with nothing behind it
is ``None`` and simply doesn't count for or against anything.
"""

import dataclasses
import datetime as dt
import math
import statistics
from collections.abc import Mapping, Sequence
from typing import Final

RECENT_DAYS: Final = 14
MIN_CHECKIN_DAYS: Final = 3  # fewer recent check-ins than this: only nudges, no wellbeing ideas
SHORT_SLEEP_MINUTES: Final = 6 * 60
LATE_BEDTIME_HOURS_AFTER_NOON: Final = 12.0 + 2.0  # 02:00 or later, on a noon-to-noon axis
ACADEMIC_STRESSORS: Final = ("exams", "deadlines", "workload")


@dataclasses.dataclass(frozen=True)
class Day:
    """One day of a student's own check-ins (the same shape the indicator models read)."""

    day: dt.date
    mood: int | None = None
    energy: int | None = None
    stress: int | None = None
    sleep_minutes: int | None = None
    sleep_quality: int | None = None
    bedtime_hour: float | None = None
    emotions: tuple[str, ...] = ()
    stressors: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class Context:
    """What the engine knows besides daily check-ins."""

    today: dt.date
    year_of_study: int | None = None
    credits: int | None = None  # credits of the courses the student is enrolled in this term
    active_goal_categories: frozenset[str] = frozenset()
    assessment_band: str | None = None  # "doing_well" | "mixed" | "lower"
    # Bands from the indicator models ("low" | "moderate" | "elevated"), when available.
    indicators: Mapping[str, str] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True)
class Signals:
    today: dt.date
    checkin_days: int  # days with any check-in in the last 14
    days_since_checkin: int | None  # None: never checked in
    mood_mean: float | None
    mood_trend: float | None  # last 7 days minus the 7 before; below 0 means it fell
    energy_mean: float | None
    stress_mean: float | None
    stress_high_share: float | None
    sleep_hours: float | None
    short_sleep_share: float | None
    late_bedtime_share: float | None
    bedtime_sd: float | None
    sleep_quality: float | None
    stressor_share: Mapping[str, float]  # share of stress answers that named each stressor
    emotion_share: Mapping[str, float]  # share of check-in days each emotion was picked
    year_of_study: int | None
    credits: int | None
    active_goal_categories: frozenset[str]
    assessment_band: str | None
    indicators: Mapping[str, str]


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _share(flags: Sequence[bool]) -> float | None:
    return sum(flags) / len(flags) if flags else None


def _bedtime_axis(hour: float) -> float:
    """Hours after noon, so 23:30 and 00:30 are an hour apart rather than 23."""
    return (hour - 12.0) % 24.0


def _sd(values: Sequence[float]) -> float | None:
    return statistics.pstdev(values) if len(values) >= 3 else None


def build(days: Sequence[Day], ctx: Context) -> Signals:
    first = ctx.today - dt.timedelta(days=RECENT_DAYS - 1)
    recent = [d for d in days if first <= d.day <= ctx.today]
    checkin_days = {d.day for d in recent}

    last = max((d.day for d in days if d.day <= ctx.today), default=None)
    days_since = (ctx.today - last).days if last is not None else None

    moods = [float(d.mood) for d in recent if d.mood is not None]
    split = ctx.today - dt.timedelta(days=6)
    newer = [float(d.mood) for d in recent if d.mood is not None and d.day >= split]
    older = [float(d.mood) for d in recent if d.mood is not None and d.day < split]
    newer_mean, older_mean = _mean(newer), _mean(older)
    trend = (
        newer_mean - older_mean
        if newer_mean is not None and older_mean is not None and len(newer) >= 2 and len(older) >= 2
        else None
    )

    stresses = [d.stress for d in recent if d.stress is not None]
    sleeps = [d.sleep_minutes for d in recent if d.sleep_minutes is not None]
    sleep_mean = _mean([float(s) for s in sleeps])
    bedtimes = [d.bedtime_hour for d in recent if d.bedtime_hour is not None]
    stress_days = [d for d in recent if d.stress is not None]

    stressor_share: dict[str, float] = {}
    if stress_days:
        names = {s for d in stress_days for s in d.stressors}
        for name in names:
            stressor_share[name] = sum(name in d.stressors for d in stress_days) / len(stress_days)
        academic = sum(any(s in d.stressors for s in ACADEMIC_STRESSORS) for d in stress_days)
        stressor_share["academic"] = academic / len(stress_days)

    emotion_days = [d for d in recent if d.emotions]
    emotion_share: dict[str, float] = {}
    if emotion_days:
        for name in {e for d in emotion_days for e in d.emotions}:
            emotion_share[name] = sum(name in d.emotions for d in emotion_days) / len(emotion_days)

    axis = [_bedtime_axis(b) for b in bedtimes]
    qualities = [float(d.sleep_quality) for d in recent if d.sleep_quality is not None]
    return Signals(
        today=ctx.today,
        checkin_days=len(checkin_days),
        days_since_checkin=days_since,
        mood_mean=_mean(moods),
        mood_trend=trend,
        energy_mean=_mean([float(d.energy) for d in recent if d.energy is not None]),
        stress_mean=_mean([float(s) for s in stresses]),
        stress_high_share=_share([s >= 4 for s in stresses]),
        sleep_hours=None if sleep_mean is None else sleep_mean / 60,
        short_sleep_share=_share([s < SHORT_SLEEP_MINUTES for s in sleeps]),
        late_bedtime_share=_share([a >= LATE_BEDTIME_HOURS_AFTER_NOON for a in axis]),
        bedtime_sd=_sd(axis),
        sleep_quality=_mean(qualities),
        stressor_share=stressor_share,
        emotion_share=emotion_share,
        year_of_study=ctx.year_of_study,
        credits=ctx.credits,
        active_goal_categories=ctx.active_goal_categories,
        assessment_band=ctx.assessment_band,
        indicators=dict(ctx.indicators),
    )


def ramp(value: float | None, start: float, end: float) -> float | None:
    """0 at ``start``, 1 at ``end``, linear in between and clamped. ``end < start`` flips it,
    so ``ramp(sleep_hours, 7.0, 5.5)`` is 0 at seven hours and 1 at five and a half."""
    if value is None or math.isnan(value):
        return None
    if start == end:
        return 1.0 if value >= end else 0.0
    t = (value - start) / (end - start)
    return min(1.0, max(0.0, t))
