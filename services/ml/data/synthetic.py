"""A synthetic cohort: 28 days of check-ins per fictional student, with indicator labels.

Each fictional student has hidden traits (academic load, social connection, sleep regularity,
career worry, money strain, coping). The labels come from those hidden traits plus label noise;
the daily check-ins are noisy, partly missing observations of the same traits. Models are
therefore asked to recover something they only see indirectly, as they would with real data.

What this data can and cannot tell us: the models can only learn the relationships written into
this generator. Scores on it measure whether the pipeline works and which algorithm suits data of
this shape. They say nothing about how well any model would do with real students. See
``model_cards/wellness-indicators.md``.
"""

import dataclasses
import datetime as dt
import hashlib
import math
from typing import Final

import numpy as np

from preprocessing.records import EMOTIONS, STRESSORS, DailyRecord

GENERATOR_VERSION: Final = "synthetic-cohort-2026.10.1"
WINDOW_END: Final = dt.date(2026, 9, 30)  # fixed, so a seed always gives the same data
STRESS_LEVELS: Final = ("low", "moderate", "high")
TABULAR_LABELS: Final = (
    "stress_level",
    "burnout_risk",
    "social_isolation",
    "sleep_lifestyle_risk",
    "career_anxiety",
)


@dataclasses.dataclass(frozen=True)
class Cohort:
    records: list[list[DailyRecord]]
    labels: dict[str, np.ndarray]
    window_end: dt.date
    seed: int

    def fingerprint(self) -> str:
        """A short hash of the labels and check-in counts, recorded with each trained model."""
        h = hashlib.sha256(f"{GENERATOR_VERSION}|{self.seed}|{len(self.records)}".encode())
        for name in TABULAR_LABELS:
            h.update(self.labels[name].tobytes())
        h.update(np.array([len(r) for r in self.records], dtype=np.int32).tobytes())
        return h.hexdigest()[:16]


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _likert(x: float) -> int:
    return int(min(5, max(1, round(x))))


def _student(
    rng: np.random.Generator, window_days: int
) -> tuple[list[DailyRecord], dict[str, int]]:
    load, connect, regular, career, money, coping = rng.normal(0.0, 1.0, 6)
    engage = rng.beta(2.0, 1.3)  # chance of checking in on a given day
    logs_sleep = rng.random() < 0.75
    tags_emotions = rng.random() < 0.85

    def noise(scale: float = 0.35) -> float:
        return float(rng.normal(0.0, scale))

    stress = 0.55 * load + 0.3 * career + 0.3 * money - 0.35 * coping - 0.15 * connect + noise()
    burnout = 0.5 * stress + 0.35 * load - 0.3 * regular - 0.3 * coping + noise()
    isolation = -0.85 * connect + 0.15 * stress + noise()
    sleep = -0.8 * regular + 0.25 * load + noise()
    worry = 0.85 * career + 0.15 * stress + noise()

    labels = {
        "stress_level": 0 if stress < -0.45 else (1 if stress < 0.55 else 2),
        "burnout_risk": int(burnout > 0.75),
        "social_isolation": int(isolation > 0.8),
        "sleep_lifestyle_risk": int(sleep > 0.7),
        "career_anxiety": int(worry > 0.8),
    }
    # Real labels are imperfect too: a few are wrong.
    for name in TABULAR_LABELS[1:]:
        if rng.random() < 0.05:
            labels[name] = 1 - labels[name]
    if rng.random() < 0.07:
        labels["stress_level"] = int(np.clip(labels["stress_level"] + rng.choice([-1, 1]), 0, 2))

    phase = rng.uniform(0, 2 * math.pi)
    start = WINDOW_END - dt.timedelta(days=window_days - 1)
    records: list[DailyRecord] = []
    for d in range(window_days):
        if rng.random() > engage:
            continue
        today = stress + 0.4 * math.sin(2 * math.pi * d / 14 + phase) + noise(0.6)
        mood = _likert(3.4 - 0.5 * today - 0.35 * isolation - 0.2 * burnout + noise(0.7))
        energy = (
            _likert(3.2 - 0.55 * burnout - 0.3 * sleep + noise(0.7)) if rng.random() < 0.8 else None
        )
        stress_answer = _likert(3.0 + 0.9 * today) if rng.random() < 0.8 else None

        sleep_minutes = quality = None
        bedtime: float | None = None
        if logs_sleep and rng.random() < 0.85:
            spread = 40 + 25 * max(0.0, sleep)
            sleep_minutes = int(np.clip(450 - 45 * sleep - 15 * load + noise(spread), 180, 720))
            bedtime = float((23.3 + 0.9 * sleep + noise(0.6 + 0.4 * max(0.0, sleep))) % 24)
            quality = _likert(3.4 - 0.6 * sleep + noise(0.8))

        emotions: tuple[str, ...] = ()
        if tags_emotions:
            weights = {
                "lonely": 1.4 * isolation - 1.8,
                "anxious": 0.8 * today + 0.5 * worry - 1.2,
                "overwhelmed": 0.8 * burnout + 0.4 * load - 1.4,
                "tired": 0.8 * sleep + 0.6 * burnout - 1.0,
                "sad": 0.7 * isolation + 0.5 * today - 1.8,
                "irritable": 0.5 * today + 0.4 * sleep - 1.8,
                "restless": 0.5 * today - 1.8,
                "calm": -0.8 * today - 0.8,
                "hopeful": -0.6 * burnout - 0.3 * worry - 1.0,
                "motivated": -0.7 * burnout - 1.0,
                "content": -0.5 * today - 0.5 * isolation - 1.2,
                "grateful": -0.4 * isolation - 1.6,
                "focused": -0.5 * burnout - 1.4,
                "energised": -0.6 * sleep - 0.4 * burnout - 1.6,
            }
            picked = [e for e in EMOTIONS if rng.random() < _sigmoid(weights[e])]
            emotions = tuple(picked[:4])

        stressors: tuple[str, ...] = ()
        if stress_answer is not None:
            weights = {
                "exams": 0.9 * load - 0.8,
                "deadlines": 0.9 * load - 0.6,
                "workload": 0.8 * load - 0.9,
                "finances": 1.1 * money - 1.4,
                "sleep": 0.9 * sleep - 1.5,
                "relationships": 0.6 * isolation - 1.8,
                "housing": -2.4,
                "career": 1.2 * worry - 1.3,
            }
            stressors = tuple(s for s in STRESSORS if rng.random() < _sigmoid(weights[s]))

        records.append(
            DailyRecord(
                day=start + dt.timedelta(days=d),
                mood=mood,
                energy=energy,
                stress=stress_answer,
                sleep_minutes=sleep_minutes,
                sleep_quality=quality,
                bedtime_hour=bedtime,
                emotions=emotions,
                stressors=stressors,
            )
        )
    return records, labels


def generate(n_students: int = 4000, *, seed: int = 20261010, window_days: int = 28) -> Cohort:
    rng = np.random.default_rng(seed)
    all_records: list[list[DailyRecord]] = []
    columns: dict[str, list[int]] = {name: [] for name in TABULAR_LABELS}
    for _ in range(n_students):
        records, labels = _student(rng, window_days)
        all_records.append(records)
        for name in TABULAR_LABELS:
            columns[name].append(labels[name])
    return Cohort(
        records=all_records,
        labels={k: np.asarray(v, dtype=np.int64) for k, v in columns.items()},
        window_end=WINDOW_END,
        seed=seed,
    )
