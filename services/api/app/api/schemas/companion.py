"""Bodies of the AI companion endpoints (``/companion``)."""

import datetime as dt
import uuid

from pydantic import BaseModel, Field

from app.application import companion as uc
from app.infrastructure.db import models as m


class CompanionStatusOut(BaseModel):
    available: bool
    # "switched_off" (by the institution or deployment) or "not_configured"
    reason: str | None
    daily_limit: int
    remaining_today: int
    keeps_history: bool
    retention_hours: int
    disclaimer: str


class ConversationOut(BaseModel):
    id: uuid.UUID
    status: str
    started_at: dt.datetime
    last_message_at: dt.datetime | None
    expires_at: dt.datetime | None


class CompanionMessageOut(BaseModel):
    id: uuid.UUID
    seq: int
    role: str  # "user" | "assistant"
    # How an assistant message was made: reply, crisis, redirect, fallback, unavailable.
    kind: str | None
    content: str
    # Crisis contacts were (or should again be) offered with this reply.
    show_support: bool
    created_at: dt.datetime


class ConversationDetailOut(BaseModel):
    conversation: ConversationOut
    messages: list[CompanionMessageOut]


class SupportContactOut(BaseModel):
    id: uuid.UUID
    label: str
    kind: str
    phone: str | None
    url: str | None
    description: str | None
    hours: str | None


class SupportOut(BaseModel):
    level: str  # "crisis" (a person was alerted) | "gentle"
    escalated: bool
    care_team_notified: bool
    about_someone_else: bool
    contacts: list[SupportContactOut]


class ExchangeOut(BaseModel):
    conversation: ConversationOut
    message: CompanionMessageOut
    reply: CompanionMessageOut
    support: SupportOut | None
    disclaimer: str


class CompanionMessageIn(BaseModel):
    # The use case trims and checks the length again (with a friendlier message).
    content: str = Field(min_length=1, max_length=4000)


def conversation_out(c: m.AIConversation) -> ConversationOut:
    return ConversationOut(
        id=c.id,
        status=c.status.value,
        started_at=c.started_at,
        last_message_at=c.last_message_at,
        expires_at=c.expires_at,
    )


def message_out(msg: m.AIMessage) -> CompanionMessageOut:
    flags = set(msg.safety_flags or ())
    return CompanionMessageOut(
        id=msg.id,
        seq=msg.seq,
        role=msg.role.value,
        kind=msg.reply_kind.value if msg.reply_kind else None,
        content=msg.content,
        show_support=bool(msg.reply_kind and (msg.crisis_flag or "support_resources" in flags)),
        created_at=msg.created_at,
    )


def support_out(sup: uc.Support) -> SupportOut:
    return SupportOut(
        level=sup.level,
        escalated=sup.escalated,
        care_team_notified=sup.care_team_notified,
        about_someone_else=sup.about_someone_else,
        contacts=[
            SupportContactOut(
                id=c.id,
                label=c.label,
                kind=c.kind.value,
                phone=c.phone,
                url=c.url,
                description=c.description,
                hours=c.hours,
            )
            for c in sup.contacts
        ],
    )
