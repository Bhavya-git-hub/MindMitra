"""Plain-language indicators derived from a student's own check-ins.

Pure functions. Wording is supportive and never diagnostic; every indicator is a description of
what the student reported, not a judgement about them.
"""

import dataclasses
import datetime as dt
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
