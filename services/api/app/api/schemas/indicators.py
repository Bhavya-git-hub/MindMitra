"""Response body for AI wellness indicators, shared by the student and therapist views.

A band (low, moderate, elevated) and the model's own level are returned; raw model scores are
not. The models are trained on synthetic data and their scores are not calibrated to real
students, so a number like 0.62 would read as a precision the indicators do not have.
"""

import datetime as dt
from typing import Literal

from pydantic import BaseModel

from app.application.wellness_indicators import Result


class IndicatorOut(BaseModel):
    indicator: str
    title: str
    meaning: str
    status: Literal["ok", "not_enough_data"]
    band: Literal["low", "moderate", "elevated"] | None
    level: str | None
    model_version: str


class IndicatorsOut(BaseModel):
    window_start: dt.date
    window_end: dt.date
    checkin_days: int
    notes_considered: int
    indicators: list[IndicatorOut]
    disclaimer: str


def indicators_out(r: Result) -> IndicatorsOut:
    return IndicatorsOut(
        window_start=r.window_start,
        window_end=r.window_end,
        checkin_days=r.checkin_days,
        notes_considered=r.notes_considered,
        indicators=[
            IndicatorOut(
                indicator=i.indicator,
                title=i.title,
                meaning=i.meaning,
                status=i.status,
                band=i.band,
                level=i.level,
                model_version=i.model_version,
            )
            for i in r.indicators
        ],
        disclaimer=r.disclaimer,
    )
