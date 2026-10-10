"""The privacy rules for group figures, as pure functions: thresholds, rounding, bands."""

import datetime as dt

import pytest

from app.domain.wellness import cohort, cohort_report
from app.domain.wellness.cohort import StudentWeek, analyse, share

MON = dt.date(2026, 9, 28)  # a Monday: the last completed week that these tests report on
STARTS = cohort.week_starts(MON + dt.timedelta(weeks=1), 4)  # "today" is the week after


def rows(n: int, **kw: object) -> list[StudentWeek]:
    return [StudentWeek(key=i, week_start=MON, checked_in=True, **kw) for i in range(n)]  # type: ignore[arg-type]


def test_week_starts_are_mondays_ending_last_week() -> None:
    # The week in progress (the one after MON) is never part of a figure.
    assert STARTS[-1] == MON and len(STARTS) == 4
    assert MON + dt.timedelta(weeks=1) not in STARTS
    assert all(d.weekday() == 0 for d in cohort.week_starts(dt.date(2026, 10, 10), 12))
    assert cohort.week_starts(dt.date(2026, 10, 10), 1) == [dt.date(2026, 9, 28)]


@pytest.mark.parametrize("n", [0, 1, 5, 9])
def test_a_group_below_the_threshold_shows_nothing(n: int) -> None:
    result = analyse(rows(n, mood=3.0), n, STARTS)
    assert result.state == "too_small"
    assert result.weeks == [] and result.contributors_band is None and result.actions == []


def test_a_group_at_the_threshold_is_shown_without_its_exact_size() -> None:
    result = analyse(rows(10, mood=3.0), 10, STARTS)
    assert result.state == "ok" and result.contributors_band == "10 to 19"
    assert result.weeks[-1].mood == 3.0


def test_an_average_needs_ten_different_students_that_week() -> None:
    nine = analyse(rows(9, mood=2.0), 30, STARTS)
    ten = analyse(rows(10, mood=2.0), 30, STARTS)
    assert nine.weeks[-1].mood is None
    assert ten.weeks[-1].mood == 2.0


def test_the_same_student_twice_counts_once() -> None:
    same = [StudentWeek(key="a", week_start=MON, mood=5.0) for _ in range(40)]
    assert analyse(same, 12, STARTS).weeks[-1].mood is None


@pytest.mark.parametrize(
    ("numerator", "denominator", "state", "percent"),
    [
        (3, 9, "hidden", None),  # group too small to say anything
        (0, 10, "few", None),
        (1, 10, "few", None),  # one struggling student is never visible
        (4, 20, "few", None),
        (5, 10, "shown", 50),
        (9, 10, "most", None),  # nor is one student who is fine
        (6, 20, "shown", 30),
        (7, 20, "shown", 35),
        (8, 21, "shown", 40),  # 38.09 rounds to the nearest 5
    ],
)
def test_shares_never_isolate_a_small_number_of_students(
    numerator: int, denominator: int, state: str, percent: int | None
) -> None:
    got = share(numerator, denominator)
    assert (got.state, got.percent) == (state, percent)


def test_no_share_reveals_a_count_below_the_minimum_group() -> None:
    for denominator in range(0, 60):
        for numerator in range(0, denominator + 1):
            got = share(numerator, denominator)
            if got.state == "shown":
                assert numerator >= cohort.MIN_GROUP
                assert denominator - numerator >= cohort.MIN_GROUP
                assert denominator >= cohort.MIN_COHORT
                assert got.percent is not None and got.percent % 5 == 0


@pytest.mark.parametrize(
    ("count", "band"),
    [
        (9, None),
        (10, "10 to 19"),
        (19, "10 to 19"),
        (20, "20 to 49"),
        (49, "20 to 49"),
        (100, "100 or more"),
    ],
)
def test_sizes_are_bands(count: int, band: str | None) -> None:
    assert cohort.size_band(count) == band


def test_averages_are_one_decimal() -> None:
    assert cohort.mean([1, 2, 2, 3, 3, 3, 4, 4, 5, 5]) == 3.2
    assert cohort.mean([1.0] * 9) is None


def test_strain_needs_two_signals_together() -> None:
    assert cohort.is_strained(1.5, 4.5, None) is True
    assert cohort.is_strained(1.5, 2.0, 480) is False  # one signal only
    assert cohort.is_strained(1.0, None, None) is None  # too little reported to say


def test_academic_stress_counts_only_students_who_did_a_stress_check() -> None:
    people = [
        StudentWeek(
            key=i,
            week_start=MON,
            stress=3.0,
            academic_stress=i < 6,
            stressors=frozenset({"exams"}) if i < 6 else frozenset({"sleep"}),
        )
        for i in range(12)
    ]
    cell = analyse(people, 12, STARTS).weeks[-1]
    assert cell.academic_stress.state == "shown" and cell.academic_stress.percent == 50


def test_stressor_mix_hides_small_slices() -> None:
    people = [
        StudentWeek(
            key=i,
            week_start=MON,
            stress=3.0,
            academic_stress=True,
            stressors=frozenset({"exams"}) | (frozenset({"housing"}) if i == 0 else frozenset()),
        )
        for i in range(12)
    ]
    named = {name for name, _ in analyse(people, 12, STARTS).stressors}
    assert "housing" not in named and "exams" in named


def test_actions_describe_the_group_and_never_a_diagnosis() -> None:
    rising = [
        StudentWeek(
            key=i,
            week_start=MON - dt.timedelta(weeks=1),
            stress=2.0,
            academic_stress=True,
            stressors=frozenset({"exams"}),
        )
        for i in range(12)
    ] + [
        StudentWeek(
            key=i, week_start=MON, stress=4.5, academic_stress=True, stressors=frozenset({"exams"})
        )
        for i in range(12)
    ]
    actions = analyse(rising, 12, STARTS).actions
    assert {a.key for a in actions} >= {"stress_rising", "academic_pressure"}
    text = " ".join(a.title + a.message for a in actions).lower()
    for word in ("diagnos", "depress", "disorder", "burnout", "student a", "who "):
        assert word not in text.replace("who did a stress check", "")


def test_csv_has_only_numbers_and_fixed_words() -> None:
    people = rows(12, mood=3.4, energy=3.0, stress=2.0)
    out = cohort_report.to_csv(analyse(people, 12, STARTS))
    lines = out.strip().splitlines()
    assert lines[0].split(",")[0] == "week_start" and len(lines) == 5
    assert "=" not in out and "@" not in out


def test_headline_for_a_small_group_says_nothing_about_numbers() -> None:
    text = " ".join(cohort_report.headline(analyse([], 3, STARTS)))
    assert "Too few" in text and not any(ch.isdigit() for ch in text)
