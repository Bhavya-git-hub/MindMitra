"""Request and response bodies of the internal API. Text in, text out; no identifiers."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
