"""How much each area of student life seems to need attention right now, and why.

Each area blends a few weighted signals (a stress average, how often a worry is named, an
indicator band when the models are available). Signals with no data are left out and the rest
are re-weighted; if too little of the evidence is present the area scores 0 and nothing is
suggested for it. Every signal that pulls a score up carries a plain-language phrase, which is
how the engine can say *why* it is suggesting something.

The weights and ramps below are judgement calls made by people, written down so they can be
reviewed and changed. They are not learned from data and they are not clinical thresholds.
"""

import dataclasses
from collections.abc import Callable
from typing import Final

from app.domain.wellness.recommender.catalog import Area
from app.domain.wellness.recommender.signals import MIN_CHECKIN_DAYS, Signals, ramp

MIN_EVIDENCE: Final = 0.5  # share of an area's weight that must have data behind it
DRIVER_FROM: Final = 0.4  # a signal this strong is worth mentioning as a reason
BAND_VALUE: Final = {"low": 0.0, "moderate": 0.6, "elevated": 1.0}
# Credits per term at which a course load starts to feel heavy, and full. Institutions count
# credits differently, so this is a development default to be set per institution later.
LOAD_START, LOAD_FULL = 15.0, 24.0


@dataclasses.dataclass(frozen=True)
class Driver:
    signal: str
    value: float  # 0 to 1, how strongly this signal points at the need
    weight: float
    phrase: str  # completes "Lately, ..."

    @property
    def pull(self) -> float:
        return self.value * self.weight


@dataclasses.dataclass(frozen=True)
class Need:
    area: Area
    score: float  # 0 to 1
    drivers: tuple[Driver, ...]  # strongest first


@dataclasses.dataclass(frozen=True)
class _Part:
    signal: str
    value: float | None
    weight: float
    phrase: str


def _blend(area: Area, parts: list[_Part]) -> Need:
    total = sum(p.weight for p in parts)
    have = [p for p in parts if p.value is not None]
    present = sum(p.weight for p in have)
    if not have or present / total < MIN_EVIDENCE:
        return Need(area, 0.0, ())
    score = sum(p.weight * (p.value or 0.0) for p in have) / present
    drivers = sorted(
        (
            Driver(p.signal, p.value, p.weight, p.phrase)
            for p in have
            if p.value is not None and p.value >= DRIVER_FROM
        ),
        key=lambda d: d.pull,
        reverse=True,
    )
    return Need(area, round(score, 3), tuple(drivers))


def _indicator(s: Signals, name: str) -> float | None:
    band = s.indicators.get(name)
    return BAND_VALUE.get(band) if band else None


def _stressor(s: Signals, name: str) -> float | None:
    # Stressors are only known on days the student answered the stress question.
    if s.stress_mean is None:
        return None
    return s.stressor_share.get(name, 0.0)


def _emotion(s: Signals, name: str) -> float | None:
    if not s.emotion_share:
        return None
    return s.emotion_share.get(name, 0.0)


def _stress(s: Signals) -> Need:
    return _blend(
        "stress",
        [
            _Part(
                "stress_mean",
                ramp(s.stress_mean, 2.5, 4.5),
                0.35,
                "your stress has been on the higher side",
            ),
            _Part(
                "stress_high_share",
                ramp(s.stress_high_share, 0.2, 0.6),
                0.15,
                "you've rated your stress as high on a number of days",
            ),
            _Part(
                "indicator_stress",
                _indicator(s, "stress_level"),
                0.3,
                "your recent check-ins point to a lot of pressure",
            ),
        ],
    )


def _academic_burnout(s: Signals) -> Need:
    load = ramp(float(s.credits), LOAD_START, LOAD_FULL) if s.credits else None
    return _blend(
        "academic_burnout",
        [
            _Part("energy_low", ramp(s.energy_mean, 3.5, 2.0), 0.15, "your energy has been low"),
            _Part(
                "stress_mean",
                ramp(s.stress_mean, 2.5, 4.5),
                0.10,
                "your stress has been on the higher side",
            ),
            _Part(
                "academic_stressors",
                ramp(_stressor(s, "academic"), 0.2, 0.7),
                0.30,
                "deadlines, exams or workload keep coming up",
            ),
            _Part("course_load", load, 0.10, "you're carrying a full course load"),
            _Part(
                "indicator_burnout",
                _indicator(s, "burnout_risk"),
                0.35,
                "your recent check-ins suggest you may be stretched thin",
            ),
        ],
    )


def _career_anxiety(s: Signals) -> Need:
    near_placements = None if s.year_of_study is None else (1.0 if s.year_of_study >= 3 else 0.0)
    return _blend(
        "career_anxiety",
        [
            _Part(
                "career_stressor",
                ramp(_stressor(s, "career"), 0.1, 0.5),
                0.35,
                "worries about your career keep coming up",
            ),
            _Part(
                "anxious_feelings",
                ramp(_emotion(s, "anxious"), 0.1, 0.5),
                0.10,
                "you've been feeling anxious",
            ),
            _Part("later_years", near_placements, 0.10, "placements are getting closer"),
            _Part(
                "indicator_career",
                _indicator(s, "career_anxiety"),
                0.45,
                "your recent check-ins point to worry about what comes next",
            ),
        ],
    )


def _social_isolation(s: Signals) -> Need:
    return _blend(
        "social_isolation",
        [
            _Part(
                "lonely_feelings",
                ramp(_emotion(s, "lonely"), 0.15, 0.5),
                0.30,
                "you've often felt lonely",
            ),
            _Part("mood_low", ramp(s.mood_mean, 3.5, 2.5), 0.10, "your mood has been low"),
            _Part(
                "relationship_stressor",
                ramp(_stressor(s, "relationships"), 0.1, 0.4),
                0.10,
                "relationships have been on your mind",
            ),
            _Part(
                "indicator_isolation",
                _indicator(s, "social_isolation"),
                0.50,
                "your recent check-ins point to feeling disconnected",
            ),
        ],
    )


def _sleep_disruption(s: Signals) -> Need:
    return _blend(
        "sleep_disruption",
        [
            _Part(
                "sleep_hours",
                ramp(s.sleep_hours, 7.0, 5.5),
                0.25,
                "you've been getting less sleep than usual",
            ),
            _Part(
                "short_nights",
                ramp(s.short_sleep_share, 0.15, 0.6),
                0.20,
                "a lot of your nights have been short",
            ),
            _Part(
                "late_bedtimes",
                ramp(s.late_bedtime_share, 0.2, 0.7),
                0.10,
                "you've been going to bed late",
            ),
            _Part(
                "irregular_bedtime",
                ramp(s.bedtime_sd, 0.75, 2.0),
                0.10,
                "your bedtime has been moving around a lot",
            ),
            _Part(
                "sleep_quality",
                ramp(s.sleep_quality, 3.5, 2.0),
                0.10,
                "your sleep hasn't felt restful",
            ),
            _Part(
                "sleep_stressor",
                ramp(_stressor(s, "sleep"), 0.1, 0.4),
                0.05,
                "sleep has been on your mind",
            ),
            _Part(
                "indicator_sleep",
                _indicator(s, "sleep_lifestyle_risk"),
                0.30,
                "your recent check-ins point to disrupted sleep",
            ),
        ],
    )


LOWER_BAND_FLOOR: Final = 0.65  # a "lower" wellbeing check is enough on its own


def _mood(s: Signals) -> Need:
    band = {"lower": 1.0, "mixed": 0.4, "doing_well": 0.0}.get(s.assessment_band or "")
    check_phrase = "your last wellbeing check showed things have felt lower"
    need = _blend(
        "mood",
        [
            _Part("mood_mean", ramp(s.mood_mean, 3.0, 2.0), 0.50, "things have felt heavier"),
            _Part("mood_falling", ramp(s.mood_trend, 0.0, -1.0), 0.15, "your mood has dipped"),
            _Part("wellbeing_check", band, 0.35, check_phrase),
        ],
    )
    if s.assessment_band == "lower" and need.score < LOWER_BAND_FLOOR:
        drivers = list(need.drivers)
        if not any(d.signal == "wellbeing_check" for d in drivers):
            drivers.append(Driver("wellbeing_check", 1.0, 0.35, check_phrase))
        drivers.sort(key=lambda d: d.pull, reverse=True)
        return Need("mood", LOWER_BAND_FLOOR, tuple(drivers))
    return need


_AREAS: Final[dict[Area, Callable[[Signals], Need]]] = {
    "stress": _stress,
    "academic_burnout": _academic_burnout,
    "career_anxiety": _career_anxiety,
    "social_isolation": _social_isolation,
    "sleep_disruption": _sleep_disruption,
    "mood": _mood,
}


def assess(s: Signals) -> dict[Area, Need]:
    """A need for every wellbeing area. With very few recent check-ins every need is 0: the
    engine would rather say nothing than guess."""
    if s.checkin_days < MIN_CHECKIN_DAYS:
        return {area: Need(area, 0.0, ()) for area in _AREAS}
    return {area: fn(s) for area, fn in _AREAS.items()}
