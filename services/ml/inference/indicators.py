"""From a student's own records to wellness indicators, using verified models.

Each indicator comes back as a band (low, moderate or elevated) with the model's score and
version, or as "not enough data" when there are too few check-ins or notes to say anything.
Nothing here is a diagnosis, and nothing here acts on a student: what to show, and to whom, is
decided by the API.
"""

import dataclasses
import datetime as dt
from collections.abc import Sequence
from typing import Final, Literal

import numpy as np

from inference.registry import LoadedModel, Registry
from preprocessing.features import MIN_CHECKIN_DAYS, engineer, to_matrix
from preprocessing.records import DailyRecord
from preprocessing.text import clean
from training.indicators import (
    DISCLAIMER,
    SENTIMENT_MEANING,
    SENTIMENT_TITLE,
    TABULAR_INDICATORS,
)

Band = Literal["low", "moderate", "elevated"]
MIN_NOTES: Final = 3
# Share of notes read as negative at which the tone indicator is moderate or elevated.
NEGATIVE_MODERATE: Final = 0.25
NEGATIVE_ELEVATED: Final = 0.5
_STRESS_BANDS: Final[dict[str, Band]] = {"low": "low", "moderate": "moderate", "high": "elevated"}


@dataclasses.dataclass(frozen=True)
class Indicator:
    indicator: str
    title: str
    meaning: str
    status: Literal["ok", "not_enough_data"]
    band: Band | None
    level: str | None  # the predicted class in the model's own words
    probabilities: dict[str, float]
    model_version: str


@dataclasses.dataclass(frozen=True)
class Assessment:
    indicators: list[Indicator]
    checkin_days: int
    notes_considered: int
    disclaimer: str = DISCLAIMER


@dataclasses.dataclass(frozen=True)
class SentimentScore:
    label: str
    probabilities: dict[str, float]


def _r(x: float) -> float:
    return round(float(x), 3)


def _binary_band(p: float, thresholds: dict[str, float]) -> Band:
    if p >= thresholds["elevated"]:
        return "elevated"
    if p >= thresholds["moderate"]:
        return "moderate"
    return "low"


def _tabular(m: LoadedModel, X: np.ndarray) -> tuple[Band, str, dict[str, float]]:
    proba = m.model.predict_proba(X)[0]
    classes = m.classes
    if m.meta["kind"] == "binary":
        p = float(proba[1])
        band = _binary_band(p, m.meta["thresholds"])
        return band, band, {"elevated": _r(p)}
    level = classes[int(np.argmax(proba))]
    return _STRESS_BANDS[level], level, {c: _r(v) for c, v in zip(classes, proba, strict=True)}


def score_texts(registry: Registry, texts: Sequence[str]) -> list[SentimentScore]:
    if not texts:
        return []
    m = registry.sentiment
    proba = m.model.predict_proba([clean(t) for t in texts])
    return [
        SentimentScore(
            label=m.classes[int(np.argmax(row))],
            probabilities={c: _r(v) for c, v in zip(m.classes, row, strict=True)},
        )
        for row in proba
    ]


def _sentiment(registry: Registry, notes: Sequence[str]) -> Indicator:
    m = registry.sentiment
    usable = [n for n in notes if clean(n)]
    if len(usable) < MIN_NOTES:
        return Indicator(
            "sentiment",
            SENTIMENT_TITLE,
            SENTIMENT_MEANING,
            "not_enough_data",
            None,
            None,
            {},
            m.version,
        )
    labels = [s.label for s in score_texts(registry, usable)]
    shares = {c: _r(labels.count(c) / len(labels)) for c in m.classes}
    negative = shares.get("negative", 0.0)
    band: Band = (
        "elevated"
        if negative >= NEGATIVE_ELEVATED
        else "moderate"
        if negative >= NEGATIVE_MODERATE
        else "low"
    )
    level = max(shares, key=lambda c: shares[c])
    return Indicator(
        "sentiment", SENTIMENT_TITLE, SENTIMENT_MEANING, "ok", band, level, shares, m.version
    )


def assess(
    registry: Registry,
    records: Sequence[DailyRecord],
    notes: Sequence[str] = (),
    *,
    window_end: dt.date | None = None,
) -> Assessment:
    row = engineer(records, window_end=window_end)
    days = int(row["checkin_days"])
    X = to_matrix([row])
    out: list[Indicator] = []
    for spec in TABULAR_INDICATORS:
        m = registry.tabular[spec.name]
        if days < MIN_CHECKIN_DAYS:
            out.append(
                Indicator(
                    spec.name,
                    spec.title,
                    spec.meaning,
                    "not_enough_data",
                    None,
                    None,
                    {},
                    m.version,
                )
            )
            continue
        band, level, probabilities = _tabular(m, X)
        out.append(
            Indicator(
                spec.name, spec.title, spec.meaning, "ok", band, level, probabilities, m.version
            )
        )
    out.append(_sentiment(registry, notes))
    return Assessment(out, days, len([n for n in notes if clean(n)]))
