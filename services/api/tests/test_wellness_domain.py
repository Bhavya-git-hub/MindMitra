"""Pure rules: the wellbeing instrument, indicators and the support prompt."""

import datetime as dt

import pytest

from app.domain.consent_scopes import BY_SCOPE, SCOPES
from app.domain.wellness import indicators, instruments
from app.domain.wellness.support_prompt import show_support_prompt
from app.infrastructure.db.enums import ConsentScope

ALL_THREE = {f"q{i}": 3 for i in range(1, 6)}


def test_instrument_scoring_and_percentage() -> None:
    assert instruments.score(ALL_THREE) == 15
    assert instruments.percentage(15) == 60
    assert instruments.percentage(25) == 100 and instruments.percentage(0) == 0


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {**ALL_THREE, "q6": 1},
        {"q1": 1},
        {**ALL_THREE, "q1": 6},
        {**ALL_THREE, "q1": -1},
        {**ALL_THREE, "q1": True},
    ],
)
def test_instrument_rejects_bad_answers(bad: dict[str, int]) -> None:
    with pytest.raises(instruments.InvalidResponses):
        instruments.score(bad)


def test_bands_use_supportive_non_clinical_words() -> None:
    assert instruments.band(25).key == "doing_well"
    assert instruments.band(15).key == "mixed"
    assert instruments.band(8).key == "lower"
    for score in range(26):
        b = instruments.band(score)
        text = f"{b.label} {b.message}".lower()
        assert not any(w in text for w in ("depress", "disorder", "diagnos", "patient", "illness"))


@pytest.mark.parametrize(
    ("avg", "key"), [(4.5, "positive"), (3.2, "steady"), (2.1, "low"), (1.2, "very_low")]
)
def test_mood_indicator(avg: float, key: str) -> None:
    ind = indicators.mood_indicator(avg)
    assert ind is not None and ind.key == key
    assert indicators.mood_indicator(None) is None


def test_stress_and_sleep_indicators() -> None:
    assert indicators.stress_indicator(1.5).key == "low"  # type: ignore[union-attr]
    assert indicators.stress_indicator(3).key == "moderate"  # type: ignore[union-attr]
    assert indicators.stress_indicator(4.5).key == "high"  # type: ignore[union-attr]
    assert indicators.sleep_indicator(450).key == "rested"  # type: ignore[union-attr]
    assert indicators.sleep_indicator(380).key == "okay"  # type: ignore[union-attr]
    assert indicators.sleep_indicator(300).key == "short"  # type: ignore[union-attr]
    assert indicators.stress_indicator(None) is None and indicators.sleep_indicator(None) is None


def test_direction_needs_both_weeks() -> None:
    assert indicators.direction(4, 3, threshold=0.3) == "up"
    assert indicators.direction(3, 4, threshold=0.3) == "down"
    assert indicators.direction(3.1, 3, threshold=0.3) == "steady"
    assert indicators.direction(None, 3, threshold=0.3) is None


def test_streak_counts_back_from_today_or_yesterday() -> None:
    today = dt.date(2026, 10, 9)
    d = dt.timedelta
    assert indicators.streak_days({today, today - d(days=1), today - d(days=2)}, today) == 3
    assert indicators.streak_days({today - d(days=1), today - d(days=2)}, today) == 2
    assert indicators.streak_days({today - d(days=2)}, today) == 0
    assert indicators.streak_days(set(), today) == 0
    assert indicators.streak_days({today, today - d(days=2)}, today) == 1


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"mood_score": 1, "stress_level": None, "note": None}, True),
        ({"mood_score": 2, "stress_level": 5, "note": None}, True),
        ({"mood_score": 3, "stress_level": 3, "note": "I want to hurt myself"}, True),
        ({"mood_score": 3, "stress_level": 3, "note": "Feeling SUICIDAL tonight"}, True),
        ({"mood_score": 3, "stress_level": 3, "note": "an ordinary tired day"}, False),
        ({"mood_score": 5, "stress_level": None, "note": None}, False),
    ],
)
def test_support_prompt(kwargs: dict[str, object], expected: bool) -> None:
    assert show_support_prompt(**kwargs) is expected  # type: ignore[arg-type]


def test_every_consent_scope_is_described_and_only_terms_are_required() -> None:
    assert {s.scope for s in SCOPES} == set(ConsentScope)
    assert [s.scope for s in SCOPES if s.required] == [ConsentScope.TERMS_AND_PRIVACY]
    assert all(BY_SCOPE[s.scope].title and BY_SCOPE[s.scope].description for s in SCOPES)
