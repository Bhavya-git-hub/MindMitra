"""Privacy rules for figures about groups of students (class, department).

Pure functions, no database. Every number a teacher sees about a group passes through here, so
the thresholds live in one place and are tested in one place.

The rules (SECURITY_ARCHITECTURE.md INV-4, ADR 0007):

* A figure is shown only when at least ``MIN_COHORT`` different students contribute to it.
* A "share of students" figure also needs ``MIN_GROUP`` students on *each* side of the split;
  otherwise it says "a few" or "nearly all" instead of a percentage, so a group of ten can
  never reveal that exactly one student is struggling.
* Percentages are rounded to the nearest 5, averages to one decimal place, and group sizes are
  given as bands, never as exact counts.
* Only fixed windows (4, 8 or 12 weeks, aligned to calendar weeks) can be asked for, so
  overlapping windows cannot be subtracted to isolate a student.

Nothing here knows who a student is: rows are keyed by an opaque id used only to count distinct
students and then discarded.
"""

import dataclasses
import datetime as dt
from collections import defaultdict
from collections.abc import Hashable, Iterable, Sequence
from typing import Literal

MIN_COHORT = 10
MIN_GROUP = 5
ALLOWED_WEEKS = (4, 8, 12)

# Stressors a student can pick that come from study life rather than the rest of life.
ACADEMIC_STRESSORS = frozenset({"exams", "deadlines", "workload"})

# "Strain" is a pattern across three self-reports, not a diagnosis of burnout.
LOW_ENERGY_AT_OR_BELOW = 2.0
HIGH_STRESS_AT_OR_ABOVE = 4.0
SHORT_SLEEP_MINUTES_BELOW = 360.0
STRAIN_SIGNALS_NEEDED = 2

ShareState = Literal["shown", "few", "most", "hidden"]


@dataclasses.dataclass(frozen=True)
class Share:
    """A proportion of a group, safe to show.

    ``shown``: ``percent`` is rounded to the nearest 5. ``few``: fewer than ``MIN_GROUP`` students
    (including none). ``most``: all but fewer than ``MIN_GROUP``. ``hidden``: the group is too
    small to say anything.
    """

    state: ShareState
    percent: int | None = None


def share(numerator: int, denominator: int) -> Share:
    if denominator < MIN_COHORT:
        return Share("hidden")
    if numerator < MIN_GROUP:
        return Share("few")
    if denominator - numerator < MIN_GROUP:
        return Share("most")
    return Share("shown", int(round(numerator * 100 / denominator / 5.0)) * 5)


def size_band(count: int) -> str | None:
    """A coarse size for a group, or ``None`` below the threshold."""
    if count < MIN_COHORT:
        return None
    if count < 20:
        return "10 to 19"
    if count < 50:
        return "20 to 49"
    if count < 100:
        return "50 to 99"
    return "100 or more"


def mean(values: Sequence[float]) -> float | None:
    """The average of at least ``MIN_COHORT`` different students' figures, to one decimal."""
    if len(values) < MIN_COHORT:
        return None
    return round(sum(values) / len(values), 1)


def is_strained(
    avg_energy: float | None, avg_stress: float | None, avg_sleep_minutes: float | None
) -> bool | None:
    """True when at least two of low energy, high stress and short sleep show together.

    ``None`` when fewer than two of the three were reported, because one signal alone says too
    little to call a pattern.
    """
    measured = [x for x in (avg_energy, avg_stress, avg_sleep_minutes) if x is not None]
    if len(measured) < STRAIN_SIGNALS_NEEDED:
        return None
    signals = 0
    if avg_energy is not None and avg_energy <= LOW_ENERGY_AT_OR_BELOW:
        signals += 1
    if avg_stress is not None and avg_stress >= HIGH_STRESS_AT_OR_ABOVE:
        signals += 1
    if avg_sleep_minutes is not None and avg_sleep_minutes < SHORT_SLEEP_MINUTES_BELOW:
        signals += 1
    return signals >= STRAIN_SIGNALS_NEEDED


@dataclasses.dataclass(frozen=True)
class StudentWeek:
    """What one consenting student reported in one calendar week (no identity beyond ``key``)."""

    key: Hashable
    week_start: dt.date
    mood: float | None = None
    energy: float | None = None
    stress: float | None = None
    academic_stress: bool | None = None  # None: no stress check that week
    stressors: frozenset[str] = frozenset()
    sleep_minutes: float | None = None
    sleep_quality: float | None = None
    checked_in: bool = False  # any mood entry that week


@dataclasses.dataclass(frozen=True)
class WeekCell:
    week_start: dt.date
    reporting_band: str | None  # how many students reported anything that week
    mood: float | None
    energy: float | None
    stress: float | None
    sleep_hours: float | None
    sleep_quality: float | None
    check_in: Share
    academic_stress: Share
    strain: Share


@dataclasses.dataclass(frozen=True)
class Action:
    key: str
    title: str
    message: str


@dataclasses.dataclass(frozen=True)
class Analytics:
    state: Literal["ok", "too_small"]
    contributors_band: str | None
    weeks: list[WeekCell]
    stressors: list[tuple[str, Share]]
    actions: list[Action]


def week_starts(today: dt.date, weeks: int) -> list[dt.date]:
    """The Mondays of the last ``weeks`` calendar weeks, oldest first, ending this week."""
    this_monday = today - dt.timedelta(days=today.weekday())
    return [this_monday - dt.timedelta(weeks=n) for n in range(weeks - 1, -1, -1)]


def _avg(values: Iterable[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def analyse(rows: Sequence[StudentWeek], contributors: int, starts: Sequence[dt.date]) -> Analytics:
    """Turn consenting students' weekly rows into figures that pass the privacy rules.

    ``contributors`` is how many consenting students the group has (not how many reported).
    """
    band = size_band(contributors)
    if band is None:
        return Analytics("too_small", None, [], [], [])

    by_week: dict[dt.date, dict[Hashable, StudentWeek]] = defaultdict(dict)
    for r in rows:
        by_week[r.week_start][r.key] = r

    cells: list[WeekCell] = []
    for start in starts:
        this = by_week.get(start, {})
        previous = by_week.get(start - dt.timedelta(weeks=1), {})
        reporting = len(this)

        moods = [r.mood for r in this.values() if r.mood is not None]
        energies = [r.energy for r in this.values() if r.energy is not None]
        stresses = [r.stress for r in this.values() if r.stress is not None]
        sleeps = [r.sleep_minutes for r in this.values() if r.sleep_minutes is not None]
        qualities = [r.sleep_quality for r in this.values() if r.sleep_quality is not None]
        sleep_mean = mean(sleeps)

        stress_checked = [r for r in this.values() if r.academic_stress is not None]
        academic = sum(1 for r in stress_checked if r.academic_stress)

        strain_known = strained = 0
        for key, r in this.items():
            prior = previous.get(key)
            verdict = is_strained(
                _avg([r.energy, prior.energy if prior else None]),
                _avg([r.stress, prior.stress if prior else None]),
                _avg([r.sleep_minutes, prior.sleep_minutes if prior else None]),
            )
            if verdict is not None:
                strain_known += 1
                strained += int(verdict)

        cells.append(
            WeekCell(
                week_start=start,
                reporting_band=size_band(reporting),
                mood=mean(moods),
                energy=mean(energies),
                stress=mean(stresses),
                sleep_hours=round(sleep_mean / 60, 1) if sleep_mean is not None else None,
                sleep_quality=mean(qualities),
                check_in=share(sum(1 for r in this.values() if r.checked_in), contributors),
                academic_stress=share(academic, len(stress_checked)),
                strain=share(strained, strain_known),
            )
        )

    return Analytics("ok", band, cells, _stressor_mix(rows, starts), supportive_actions(cells))


def _stressor_mix(
    rows: Sequence[StudentWeek], starts: Sequence[dt.date]
) -> list[tuple[str, Share]]:
    """How many of the students who did a stress check in the window named each stressor."""
    window = set(starts)
    named: dict[str, set[Hashable]] = defaultdict(set)
    checked: set[Hashable] = set()
    for r in rows:
        if r.week_start not in window or r.academic_stress is None:
            continue
        checked.add(r.key)
        for stressor in r.stressors:
            named[stressor].add(r.key)
    mix = [(name, share(len(keys), len(checked))) for name, keys in named.items()]
    return sorted(
        (item for item in mix if item[1].state in ("shown", "most")),
        key=lambda item: (-(item[1].percent or 100), item[0]),
    )


def _latest(cells: Sequence[WeekCell], field: str, n: int = 2) -> list[float]:
    return [v for c in cells if (v := getattr(c, field)) is not None][-n:]


def supportive_actions(cells: Sequence[WeekCell]) -> list[Action]:
    """Plain suggestions for the group as a whole, from the shape of the last few weeks.

    They describe the group, never a person, and never mention a diagnosis.
    """
    actions: list[Action] = []
    stress = _latest(cells, "stress")
    mood = _latest(cells, "mood")
    if len(stress) == 2 and stress[1] - stress[0] >= 0.3:
        actions.append(
            Action(
                "stress_rising",
                "Stress has been rising",
                "Self-reported stress went up over the last two weeks with enough data to show. "
                "Spacing deadlines or offering a short extension window can take pressure off.",
            )
        )
    if len(mood) == 2 and mood[0] - mood[1] >= 0.3:
        actions.append(
            Action(
                "mood_dipping",
                "Mood has dipped",
                "Average mood is lower than the week before. A short check-in with the class "
                "about workload, and a reminder of where support is, can help.",
            )
        )
    latest = cells[-1] if cells else None
    if latest is not None:
        if latest.academic_stress.state in ("shown", "most") and (
            latest.academic_stress.percent is None or latest.academic_stress.percent >= 50
        ):
            actions.append(
                Action(
                    "academic_pressure",
                    "Many students point to study pressure",
                    "Most students who did a stress check named exams, deadlines or workload. "
                    "Clear expectations and early notice of deadlines tend to help.",
                )
            )
        if latest.strain.state == "most" or (
            latest.strain.state == "shown" and (latest.strain.percent or 0) >= 15
        ):
            actions.append(
                Action(
                    "strain_signs",
                    "Signs of strain are showing",
                    "More students than usual report low energy, high stress or short sleep "
                    "together. Reminding everyone that support is available, without singling "
                    "anyone out, is a good next step.",
                )
            )
        if latest.check_in.state == "few":
            actions.append(
                Action(
                    "low_participation",
                    "Few students are checking in",
                    "Not many students checked in this week, so the figures may not reflect "
                    "the group. A general reminder that check-ins are private can help.",
                )
            )
    return actions
