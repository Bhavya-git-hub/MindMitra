"""Feature engineering: 28 days of daily records become one row of numbers.

Missing values stay NaN (a student who never logs sleep has no sleep features); the model
pipelines impute them and add "was missing" flags. Values outside their valid range are
dropped rather than clipped, so a bad input cannot pass for an extreme score.
"""

import datetime as dt
import math
from collections.abc import Iterable, Sequence
from typing import Final

import numpy as np

from preprocessing.records import EMOTIONS, NEGATIVE_EMOTIONS, STRESSORS, DailyRecord

WINDOW_DAYS: Final = 28
# Below this many check-in days the indicators say "not enough data" instead of guessing.
MIN_CHECKIN_DAYS: Final = 7

_TRACKED_EMOTIONS: Final = ("lonely", "anxious", "overwhelmed", "tired", "sad", "calm", "hopeful")

FEATURES: Final[tuple[str, ...]] = (
    "checkin_days",
    "longest_gap_days",
    "mood_mean",
    "mood_sd",
    "mood_slope",
    "energy_mean",
    "stress_mean",
    "stress_high_share",
    "sleep_hours_mean",
    "sleep_hours_sd",
    "short_sleep_share",
    "sleep_quality_mean",
    "late_bedtime_share",
    "bedtime_sd",
    "negative_emotion_share",
    "positive_emotion_share",
    *(f"emotion_{e}_share" for e in _TRACKED_EMOTIONS),
    *(f"stressor_{s}_share" for s in STRESSORS),
)


def _in_range(value: float | None, low: float, high: float) -> float | None:
    if value is None or not math.isfinite(value) or not low <= value <= high:
        return None
    return float(value)


def _mean(xs: Sequence[float]) -> float:
    return float(np.mean(xs)) if xs else math.nan


def _sd(xs: Sequence[float]) -> float:
    return float(np.std(xs)) if len(xs) >= 2 else math.nan


def _slope_per_week(days: Sequence[int], ys: Sequence[float]) -> float:
    """Least-squares trend in units per week; NaN with fewer than 4 points or one day."""
    if len(ys) < 4 or len(set(days)) < 2:
        return math.nan
    slope = float(np.polyfit(np.asarray(days, float), np.asarray(ys, float), 1)[0])
    return slope * 7.0


def _bedtime_axis(hour: float) -> float:
    """Hours after noon, so 23:00 and 01:00 are two hours apart, not twenty-two."""
    return hour - 12.0 if hour >= 12.0 else hour + 12.0


def _longest_gap(days: set[int], window: int) -> int:
    longest = run = 0
    for d in range(window):
        run = 0 if d in days else run + 1
        longest = max(longest, run)
    return longest


def engineer(
    records: Iterable[DailyRecord],
    *,
    window_end: dt.date | None = None,
    window_days: int = WINDOW_DAYS,
) -> dict[str, float]:
    """One feature row from the records in the window ending on ``window_end`` (inclusive)."""
    recs = sorted(records, key=lambda r: r.day)
    end = window_end or (recs[-1].day if recs else dt.date.today())
    start = end - dt.timedelta(days=window_days - 1)
    by_day: dict[dt.date, DailyRecord] = {}
    for r in recs:
        if start <= r.day <= end:
            by_day[r.day] = r  # a later record for the same day wins
    rows = [by_day[d] for d in sorted(by_day)]
    index = [(r.day - start).days for r in rows]

    mood = [
        (i, v)
        for i, r in zip(index, rows, strict=True)
        if (v := _in_range(r.mood, 1, 5)) is not None
    ]
    energy = [v for r in rows if (v := _in_range(r.energy, 1, 5)) is not None]
    stress = [v for r in rows if (v := _in_range(r.stress, 1, 5)) is not None]
    sleep_h = [v / 60.0 for r in rows if (v := _in_range(r.sleep_minutes, 60, 960)) is not None]
    quality = [v for r in rows if (v := _in_range(r.sleep_quality, 1, 5)) is not None]
    bedtimes = [
        _bedtime_axis(v) for r in rows if (v := _in_range(r.bedtime_hour, 0, 24)) is not None
    ]

    out: dict[str, float] = {
        "checkin_days": float(len(rows)),
        "longest_gap_days": float(_longest_gap(set(index), window_days)),
        "mood_mean": _mean([v for _, v in mood]),
        "mood_sd": _sd([v for _, v in mood]),
        "mood_slope": _slope_per_week([i for i, _ in mood], [v for _, v in mood]),
        "energy_mean": _mean(energy),
        "stress_mean": _mean(stress),
        "stress_high_share": _mean([1.0 if v >= 4 else 0.0 for v in stress]),
        "sleep_hours_mean": _mean(sleep_h),
        "sleep_hours_sd": _sd(sleep_h),
        "short_sleep_share": _mean([1.0 if h < 6.0 else 0.0 for h in sleep_h]),
        "sleep_quality_mean": _mean(quality),
        # After 01:00 is 13 or more hours after noon.
        "late_bedtime_share": _mean([1.0 if b >= 13.0 else 0.0 for b in bedtimes]),
        "bedtime_sd": _sd(bedtimes),
    }

    tagged = [r for r in rows if r.emotions]
    emotion_sets = [{e for e in r.emotions if e in EMOTIONS} for r in tagged]
    n_tags = sum(len(s) for s in emotion_sets)
    neg = sum(len(s & NEGATIVE_EMOTIONS) for s in emotion_sets)
    out["negative_emotion_share"] = neg / n_tags if n_tags else math.nan
    out["positive_emotion_share"] = (n_tags - neg) / n_tags if n_tags else math.nan
    for e in _TRACKED_EMOTIONS:
        out[f"emotion_{e}_share"] = (
            sum(e in s for s in emotion_sets) / len(emotion_sets) if emotion_sets else math.nan
        )

    # Stressors are asked with the stress question, so the share is over days with a stress
    # answer (a day without one says nothing about stressors).
    stress_days = [r for r in rows if r.stress is not None]
    for s in STRESSORS:
        out[f"stressor_{s}_share"] = (
            sum(s in r.stressors for r in stress_days) / len(stress_days)
            if stress_days
            else math.nan
        )
    return {name: out[name] for name in FEATURES}


def to_matrix(rows: Sequence[dict[str, float]]) -> np.ndarray:
    """Feature rows in ``FEATURES`` order, as a float matrix (NaN where missing)."""
    return np.array([[row[name] for name in FEATURES] for row in rows], dtype=float)
