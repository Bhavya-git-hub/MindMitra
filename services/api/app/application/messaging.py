"""Private messages between a student and a therapist on the same care team.

A conversation is the pair (student, therapist). Either participant may read and write it while
the care-team link is active; nobody else can, whatever their role (teachers and administrators
included). After the link ends the student can still read their own history; nobody can write.
Message bodies are encrypted at rest and are never written to the audit log. Real-time events
carry only ids, so the content is always fetched through these checks.
"""

import dataclasses
import datetime as dt
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.access import NotFound, enforce, has_active_care_link
from app.application.errors import InvalidInput
from app.application.notifications import notify
from app.application.therapist_access import require_verified
from app.application.timeutil import now_utc
from app.domain.auth.permissions import Role
from app.domain.auth.policies import (
    Principal,
    can_message_in_conversation,
    can_read_conversation_history,
)
from app.domain.wellness.support_prompt import show_support_prompt
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import NotificationType
from app.infrastructure.db.ids import uuid7
from app.infrastructure.events import queue_event

MAX_BODY_LENGTH = 4000
PREVIEW_LENGTH = 90


@dataclasses.dataclass
class Conversation:
    other_id: uuid.UUID
    other_name: str
    active: bool  # still on the same care team
    last_message_at: dt.datetime | None
    last_message_preview: str | None
    unread_count: int


def _parties(actor: Principal, other_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """(student_id, therapist_id) for a conversation between the caller and ``other_id``."""
    if actor.role is Role.STUDENT:
        return actor.user_id, other_id
    return other_id, actor.user_id


async def _authorize(
    db: AsyncSession, actor: Principal, other_id: uuid.UUID, action: str, *, write: bool
) -> tuple[uuid.UUID, uuid.UUID]:
    if actor.role is Role.THERAPIST:
        await require_verified(db, actor, action)
    other = await db.get(m.User, other_id)
    if other is None or other.institution_id != actor.institution_id:
        raise NotFound
    student_id, therapist_id = _parties(actor, other_id)
    linked = await has_active_care_link(
        db, therapist_id=therapist_id, student_id=student_id, now=now_utc()
    )
    history = False
    if not write and not linked and actor.user_id == student_id:
        history = (
            await db.scalar(
                select(m.Message.id)
                .where(
                    m.Message.student_id == student_id,
                    m.Message.therapist_id == therapist_id,
                    m.Message.institution_id == actor.institution_id,
                )
                .limit(1)
            )
            is not None
        )
    decision = (
        can_message_in_conversation(
            actor,
            conversation_institution_id=other.institution_id,
            student_id=student_id,
            therapist_id=therapist_id,
            has_active_care_link=linked,
        )
        if write
        else can_read_conversation_history(
            actor,
            conversation_institution_id=other.institution_id,
            student_id=student_id,
            therapist_id=therapist_id,
            has_active_care_link=linked,
            has_history=history,
        )
    )
    enforce(
        decision,
        action=action,
        resource_type="message",
        subject_student_id=student_id,
    )
    return student_id, therapist_id


async def list_conversations(db: AsyncSession, actor: Principal) -> list[Conversation]:
    """Care-team counterparts plus anyone the caller has already exchanged messages with."""
    if actor.role is Role.THERAPIST:
        await require_verified(db, actor, "conversation.list")
    now = now_utc()
    if actor.role is Role.STUDENT:
        link_col, other_col, msg_other = (
            m.CareTeamMember.student_id,
            m.CareTeamMember.therapist_id,
            m.Message.therapist_id,
        )
        msg_mine = m.Message.student_id
    else:
        link_col, other_col, msg_other = (
            m.CareTeamMember.therapist_id,
            m.CareTeamMember.student_id,
            m.Message.student_id,
        )
        msg_mine = m.Message.therapist_id
    active_ids = set(
        await db.scalars(
            select(other_col).where(
                link_col == actor.user_id,
                m.CareTeamMember.institution_id == actor.institution_id,
                m.CareTeamMember.starts_at <= now,
                (m.CareTeamMember.ends_at.is_(None)) | (m.CareTeamMember.ends_at > now),
            )
        )
    )
    talked = set(
        await db.scalars(
            select(msg_other)
            .where(msg_mine == actor.user_id, m.Message.institution_id == actor.institution_id)
            .distinct()
        )
    )
    out: list[Conversation] = []
    for other_id in active_ids | talked:
        name = await db.scalar(select(m.User.full_name).where(m.User.id == other_id)) or ""
        student_id, therapist_id = _parties(actor, other_id)
        last = await db.scalar(
            select(m.Message)
            .where(m.Message.student_id == student_id, m.Message.therapist_id == therapist_id)
            .order_by(m.Message.created_at.desc())
            .limit(1)
        )
        unread = await db.scalar(
            select(func.count())
            .select_from(m.Message)
            .where(
                m.Message.student_id == student_id,
                m.Message.therapist_id == therapist_id,
                m.Message.sender_id != actor.user_id,
                m.Message.read_at.is_(None),
            )
        )
        out.append(
            Conversation(
                other_id=other_id,
                other_name=name,
                active=other_id in active_ids,
                last_message_at=last.created_at if last else None,
                last_message_preview=(last.body[:PREVIEW_LENGTH] if last else None),
                unread_count=int(unread or 0),
            )
        )
    out.sort(
        key=lambda c: c.last_message_at or dt.datetime.min.replace(tzinfo=dt.UTC), reverse=True
    )
    return out


async def get_messages(
    db: AsyncSession,
    actor: Principal,
    other_id: uuid.UUID,
    *,
    limit: int,
    before: dt.datetime | None,
) -> list[m.Message]:
    student_id, therapist_id = await _authorize(db, actor, other_id, "message.list", write=False)
    stmt = select(m.Message).where(
        m.Message.student_id == student_id,
        m.Message.therapist_id == therapist_id,
        m.Message.institution_id == actor.institution_id,
    )
    if before is not None:
        stmt = stmt.where(m.Message.created_at < before)
    rows = list(await db.scalars(stmt.order_by(m.Message.created_at.desc()).limit(min(limit, 200))))
    rows.reverse()  # oldest first for display
    return rows


@dataclasses.dataclass
class SentMessage:
    message: m.Message
    support_suggested: bool


async def send_message(
    db: AsyncSession,
    actor: Principal,
    other_id: uuid.UUID,
    body: str,
    client_msg_id: uuid.UUID | None,
) -> SentMessage:
    student_id, therapist_id = await _authorize(db, actor, other_id, "message.create", write=True)
    text = body.strip()
    if not text:
        raise InvalidInput("Please write a message first.")
    if len(text) > MAX_BODY_LENGTH:
        raise InvalidInput(f"Messages can be up to {MAX_BODY_LENGTH} characters.")

    if client_msg_id is not None:  # a retried request must not create a second message
        existing = await db.scalar(
            select(m.Message).where(
                m.Message.sender_id == actor.user_id, m.Message.client_msg_id == client_msg_id
            )
        )
        if existing is not None:
            if (existing.student_id, existing.therapist_id) != (student_id, therapist_id):
                raise InvalidInput("That message id was already used.")
            return SentMessage(existing, False)

    now = now_utc()
    message = m.Message(
        id=uuid7(),
        institution_id=actor.institution_id,
        student_id=student_id,
        therapist_id=therapist_id,
        sender_id=actor.user_id,
        body=text,
        client_msg_id=client_msg_id,
        crisis_checked_at=now if actor.role is Role.STUDENT else None,
    )
    db.add(message)
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError as exc:
        raise InvalidInput("That message id was already used.") from exc
    await notify(
        db,
        institution_id=actor.institution_id,
        user_id=other_id,
        type=NotificationType.NEW_MESSAGE,
        title="You have a new message",
        payload={"message_id": str(message.id)},
    )
    # The recipient's open tabs, and the sender's other tabs, pick the message up at once.
    queue_event(
        db, other_id, {"type": "message", "with": str(actor.user_id), "message_id": str(message.id)}
    )
    queue_event(
        db, actor.user_id, {"type": "message", "with": str(other_id), "message_id": str(message.id)}
    )
    await db.commit()
    suggested = actor.role is Role.STUDENT and show_support_prompt(
        mood_score=3, stress_level=None, note=text
    )
    return SentMessage(message, suggested)


async def mark_read(db: AsyncSession, actor: Principal, other_id: uuid.UUID) -> int:
    student_id, therapist_id = await _authorize(db, actor, other_id, "message.read", write=False)
    result = await db.execute(
        update(m.Message)
        .where(
            m.Message.student_id == student_id,
            m.Message.therapist_id == therapist_id,
            m.Message.institution_id == actor.institution_id,
            m.Message.sender_id != actor.user_id,
            m.Message.read_at.is_(None),
        )
        .values(read_at=now_utc())
    )
    count = int(getattr(result, "rowcount", 0) or 0)
    if count:  # read receipts for the sender, and the reader's other tabs clear their badge
        queue_event(db, other_id, {"type": "message_read", "with": str(actor.user_id)})
        queue_event(db, actor.user_id, {"type": "message_read", "with": str(other_id)})
    await db.commit()
    return count
