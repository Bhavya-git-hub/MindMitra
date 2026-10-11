"""A stand-in for the AI service's indicator endpoint, shared by the API tests that need one.

It records every call (window end, the days sent, the notes sent) so tests can check what left
the API, and it answers with the bands a test configures. The models have their own tests in
``services/ml/tests``.
"""

import dataclasses
import datetime as dt
from collections.abc import Mapping, Sequence

from app.infrastructure.ml_client import (
    DayRecord,
    Indicator,
    IndicatorReport,
    IndicatorsUnavailable,
)

DISCLAIMER = "These are wellness indicators. They are not a diagnosis."
DEFAULT_BANDS: Mapping[str, str] = {
    "stress_level": "moderate",
    "burnout_risk": "low",
    "sentiment": "elevated",
}


def indicator(name: str, band: str) -> Indicator:
    return Indicator(name, name.title(), "What it means.", "ok", band, band, {"x": 0.4}, "v1")  # type: ignore[arg-type]


@dataclasses.dataclass
class Call:
    window_end: dt.date
    days: list[DayRecord]
    notes: list[str]


class FakeIndicators:
    def __init__(self, bands: Mapping[str, str] | None = None) -> None:
        self.down = False
        self.bands: dict[str, str] = dict(DEFAULT_BANDS if bands is None else bands)
        self.calls: list[Call] = []

    async def indicators(
        self, window_end: dt.date, days: Sequence[DayRecord], notes: Sequence[str]
    ) -> IndicatorReport:
        if self.down:
            raise IndicatorsUnavailable("status 503")
        self.calls.append(Call(window_end, list(days), list(notes)))
        return IndicatorReport(
            tuple(indicator(k, v) for k, v in self.bands.items()),
            checkin_days=len(days),
            notes_considered=len(notes),
            disclaimer=DISCLAIMER,
        )
