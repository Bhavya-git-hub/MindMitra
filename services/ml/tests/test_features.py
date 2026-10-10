"""Feature engineering: the numbers a model sees for a student's 28 days."""

import datetime as dt
import math

import pytest

from preprocessing.features import FEATURES, engineer, to_matrix
from preprocessing.records import DailyRecord
from preprocessing.text import MAX_NOTE_CHARS, clean

END = dt.date(2026, 9, 30)


def day(offset: int, **values: object) -> DailyRecord:
    return DailyRecord(day=END - dt.timedelta(days=offset), **values)  # type: ignore[arg-type]


def test_every_feature_is_present_and_ordered() -> None:
    row = engineer([day(0, mood=3)], window_end=END)
    assert list(row) == list(FEATURES)
    assert to_matrix([row]).shape == (1, len(FEATURES))


def test_no_records_means_zero_days_and_missing_values() -> None:
    row = engineer([], window_end=END)
    assert row["checkin_days"] == 0
    assert row["longest_gap_days"] == 28
    assert math.isnan(row["mood_mean"])
    assert math.isnan(row["sleep_hours_mean"])


def test_averages_shares_and_the_longest_gap() -> None:
    records = [
        day(
            0, mood=4, stress=5, stressors=("exams", "career"), sleep_minutes=300, bedtime_hour=2.0
        ),
        day(1, mood=2, stress=2, stressors=("exams",), sleep_minutes=480, bedtime_hour=23.0),
        day(10, mood=3, emotions=("lonely", "calm")),
    ]
    row = engineer(records, window_end=END)
    assert row["checkin_days"] == 3
    assert row["longest_gap_days"] == 17  # days 0 to 16 of the window are empty
    assert row["mood_mean"] == pytest.approx(3.0)
    assert row["stress_high_share"] == pytest.approx(0.5)
    assert row["stressor_exams_share"] == pytest.approx(1.0)
    assert row["stressor_career_share"] == pytest.approx(0.5)
    assert row["short_sleep_share"] == pytest.approx(0.5)
    assert row["late_bedtime_share"] == pytest.approx(0.5)  # 02:00 is late, 23:00 is not
    assert row["bedtime_sd"] == pytest.approx(1.5)  # 23:00 and 02:00 are three hours apart
    assert row["emotion_lonely_share"] == pytest.approx(1.0)
    assert row["negative_emotion_share"] == pytest.approx(0.5)


def test_a_falling_mood_has_a_negative_slope() -> None:
    records = [day(i, mood=5 - i // 2) for i in range(8)]  # newest day is the best
    assert engineer(records, window_end=END)["mood_slope"] > 0
    falling = [day(i, mood=1 + i // 2) for i in range(8)]
    assert engineer(falling, window_end=END)["mood_slope"] < 0


def test_out_of_range_values_are_dropped_not_clipped() -> None:
    row = engineer([day(0, mood=9, sleep_minutes=5000, bedtime_hour=30.0)], window_end=END)
    assert math.isnan(row["mood_mean"])
    assert math.isnan(row["sleep_hours_mean"])
    assert math.isnan(row["late_bedtime_share"])


def test_only_the_window_counts_and_unknown_words_are_ignored() -> None:
    records = [
        day(0, mood=4, emotions=("ecstatic", "calm")),
        day(40, mood=1),  # outside the 28 days
    ]
    row = engineer(records, window_end=END)
    assert row["checkin_days"] == 1
    assert row["mood_mean"] == 4
    assert row["positive_emotion_share"] == 1.0  # "ecstatic" is not a word the app offers


def test_note_cleaning_only_trims_space_and_length() -> None:
    assert clean("  so   tired \n today ") == "so tired today"
    assert len(clean("a" * (MAX_NOTE_CHARS + 50))) == MAX_NOTE_CHARS
