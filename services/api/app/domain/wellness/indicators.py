"""Plain-language indicators derived from a student's own check-ins.

Pure functions. Wording is supportive and never diagnostic; every indicator is a description of
what the student reported, not a judgement about them.
"""

import dataclasses
import datetime as dt
import math
from collections.abc import Collection, Sequence

Direction = str  # "up" | "steady" | "down"


@dataclasses.dataclass(frozen=True)
class Indicator:
    key: str
    label: str


def average(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def mood_indicator(avg: float | None) -> Indicator | None:
    if avg is None:
        return None
    if avg >= 4:
        return Indicator("positive", "Feeling good")
    if avg >= 3:
        return Indicator("steady", "Steady")
    if avg >= 2:
        return Indicator("low", "A bit low")
    return Indicator("very_low", "Feeling low")


def stress_indicator(avg: float | None) -> Indicator | None:
    if avg is None:
        return None
    if avg <= 2:
        return Indicator("low", "Low stress")
    if avg <= 3.5:
        return Indicator("moderate", "Moderate stress")
    return Indicator("high", "High stress")


def sleep_indicator(avg_minutes: float | None) -> Indicator | None:
    if avg_minutes is None:
        return None
    if avg_minutes >= 420:
        return Indicator("rested", "Well rested")
    if avg_minutes >= 360:
        return Indicator("okay", "Getting by")
    return Indicator("short", "Short on sleep")


def direction(
    current: float | None, previous: float | None, *, threshold: float
) -> Direction | None:
    if current is None or previous is None:
        return None
    delta = current - previous
    if delta > threshold:
        return "up"
    if delta < -threshold:
        return "down"
    return "steady"


def streak_days(check_in_days: Collection[dt.date], today: dt.date) -> int:
    """Consecutive days with a check-in ending today, or yesterday if today has none yet."""
    cursor = today if today in check_in_days else today - dt.timedelta(days=1)
    count = 0
    while cursor in check_in_days:
        count += 1
        cursor -= dt.timedelta(days=1)
    return count


def _scale_to_percent(value: float) -> float:
    """A 1-5 self-report scale mapped onto 0-100."""
    return (value - 1) / 4 * 100


def wellness_index(
    mood: float | None, stress: float | None, sleep_quality: float | None
) -> int | None:
    """A transparent 0-100 summary of what a student reported, or None without enough.

    Each component is a 1-5 self-report: mood and sleep quality count as they are (1 -> 0,
    5 -> 100) and stress is inverted, so lower reported stress gives a higher figure
    (``(5 - stress) / 4 * 100``). The index is the plain average of the components that are
    present, and needs at least two of the three; otherwise it is None.

    This is a self-reported summary to help someone see their own patterns over time. It is
    not a clinical measure and says nothing about a person's health.
    """
    parts = [
        part
        for part in (
            None if mood is None else _scale_to_percent(mood),
            None if stress is None else _scale_to_percent(6 - stress),
            None if sleep_quality is None else _scale_to_percent(sleep_quality),
        )
        if part is not None
    ]
    if len(parts) < 2:
        return None
    return math.floor(sum(parts) / len(parts) + 0.5)  # halves round up, not to even


def goal_progress_percent(current_value: float, target_value: float | None) -> int | None:
    """How far along a goal is, 0-100, or None when it has no target to measure against."""
    if not target_value:
        return None
    return min(100, round(current_value * 100 / target_value))
