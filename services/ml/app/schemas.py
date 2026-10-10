"""Request and response bodies of the internal API. Text in, text out; no identifiers."""

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from preprocessing.text import MAX_NOTE_CHARS
from safety.input_guard import MAX_MESSAGE_CHARS


class TurnIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class RespondIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    # Oldest first, the current conversation only.
    history: list[TurnIn] = Field(default_factory=list, max_length=60)


class CrisisOut(BaseModel):
    action: Literal["none", "review", "escalate"]
    category: str | None
    severity: Literal["low", "moderate", "high", "imminent"] | None
    rules: list[str]
    third_person: bool
    requires_human: bool


class RespondOut(BaseModel):
    kind: Literal["reply", "crisis", "redirect", "fallback", "unavailable"]
    reply: str | None
    crisis: CrisisOut
    topic: str
    flags: list[str]
    model_version: str
    disclaimer: str


class ModelsOut(BaseModel):
    provider_model: str
    prompt_version: str
    rules_version: str
    # Wellness indicator models; empty with a reason when they are not loaded.
    indicator_models: dict[str, str]
    indicators_unavailable: str | None


Word = Annotated[str, StringConstraints(min_length=1, max_length=60)]
Note = Annotated[str, StringConstraints(min_length=1, max_length=MAX_NOTE_CHARS)]


class DayIn(BaseModel):
    """One day of a student's own check-ins. Every value is optional."""

    model_config = ConfigDict(extra="forbid")

    day: dt.date
    mood: int | None = Field(default=None, ge=1, le=5)
    energy: int | None = Field(default=None, ge=1, le=5)
    stress: int | None = Field(default=None, ge=1, le=5)
    sleep_minutes: int | None = Field(default=None, ge=0, le=1440)
    sleep_quality: int | None = Field(default=None, ge=1, le=5)
    bedtime_hour: float | None = Field(default=None, ge=0, lt=24)
    emotions: list[Word] = Field(default_factory=list, max_length=14)
    stressors: list[Word] = Field(default_factory=list, max_length=8)


class IndicatorsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The last day of the 28-day window (the student's local today).
    window_end: dt.date
    days: list[DayIn] = Field(default_factory=list, max_length=62)
    # Notes the student wrote with those check-ins, for the tone indicator only.
    notes: list[Note] = Field(default_factory=list, max_length=60)


class IndicatorOut(BaseModel):
    indicator: str
    title: str
    meaning: str
    status: Literal["ok", "not_enough_data"]
    band: Literal["low", "moderate", "elevated"] | None
    level: str | None
    probabilities: dict[str, float]
    model_version: str


class IndicatorsOut(BaseModel):
    indicators: list[IndicatorOut]
    checkin_days: int
    notes_considered: int
    disclaimer: str


class SentimentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    texts: list[Note] = Field(min_length=1, max_length=50)


class SentimentItemOut(BaseModel):
    label: str
    probabilities: dict[str, float]


class SentimentOut(BaseModel):
    results: list[SentimentItemOut]
    model_version: str
    disclaimer: str
