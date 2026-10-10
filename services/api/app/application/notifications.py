"""Notifications: the one way the application tells a person something happened.

``notify`` writes the in-app notification, queues a real-time event for the recipient's open
connections (sent only after commit), and, when the institution has switched e-mail on, a
delivery for the dispatcher. Titles are fixed phrases and payloads hold identifiers and fixed
event names only (checked here), so nothing anyone wrote can reach a notification, an e-mail or
a lock screen.

``dispatch_due`` sends pending deliveries through the configured providers with retries. A
channel without a provider is recorded as skipped rather than silently dropped.
"""

import dataclasses
import datetime as dt
import re
import uuid
from typing import Any, Final

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application import institution_settings
from app.application.access import NotFound
from app.application.errors import InvalidInput
from app.application.timeutil import now_utc
from app.domain.auth.policies import Principal
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import (
    DeliveryStatus,
    NotificationChannel,
    NotificationPriority,
    NotificationType,
    UserStatus,
)
from app.infrastructure.db.ids import uuid7
from app.infrastructure.events import queue_event
from app.infrastructure.notifications.providers import DeliveryError, Providers, outbound

MAX_TITLE: Final = 160
ALLOWED_PAYLOAD_KEYS: Final = frozenset(
    {"appointment_id", "event", "message_id", "recommendation_id", "alert_id", "request_id"}
)
_SLUG = re.compile(r"^[a-z0-9_]{1,40}$")
MAX_ATTEMPTS: Final = 5
BACKOFF: Final = (
    dt.timedelta(minutes=1),
    dt.timedelta(minutes=5),
    dt.timedelta(minutes=30),
    dt.timedelta(hours=2),
)


def _check_payload(payload: dict[str, Any]) -> dict[str, str]:
    clean: dict[str, str] = {}
    for key, value in payload.items():
        if key not in ALLOWED_PAYLOAD_KEYS:
            raise ValueError(f"notification payload key not allowed: {key}")
        text = str(value)
        if key == "event":
            if not _SLUG.match(text):
                raise ValueError("notification event must be a short fixed name")
        else:
            uuid.UUID(text)  # identifiers only
        clean[key] = text
    return clean


async def notify(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID,
    user_id: uuid.UUID,
    type: NotificationType,
    title: str,
    payload: dict[str, Any] | None = None,
    priority: NotificationPriority = NotificationPriority.NORMAL,
) -> m.Notification:
    if not title or len(title) > MAX_TITLE:
        raise ValueError("notification title must be 1 to 160 characters")
    note = m.Notification(
        id=uuid7(),
        institution_id=institution_id,
        user_id=user_id,
        type=type,
        priority=priority,
        title=title,
        payload=_check_payload(payload or {}),
    )
    db.add(note)
    config = await institution_settings.load(db, institution_id)
    if config.notifications.email_enabled:
        # No ORM relationship ties the two rows, so write the notification first for the FK.
        await db.flush()
        db.add(
            m.Delivery(
                id=uuid7(),
                institution_id=institution_id,
                notification_id=note.id,
                user_id=user_id,
                channel=NotificationChannel.EMAIL,
            )
        )
    queue_event(
        db,
        user_id,
        {
            "type": "notification",
            "id": str(note.id),
            "notification_type": type.value,
            "title": title,
        },
    )
    return note


# ---- the inbox ------------------------------------------------------------------------------


@dataclasses.dataclass
class Inbox:
    items: list[m.Notification]
    unread: int


async def inbox(
    db: AsyncSession,
    actor: Principal,
    *,
    unread_only: bool,
    before: dt.datetime | None,
    limit: int,
) -> Inbox:
    if not 1 <= limit <= 100:
        raise InvalidInput("limit must be between 1 and 100.")
    stmt = select(m.Notification).where(
        m.Notification.user_id == actor.user_id,
        m.Notification.institution_id == actor.institution_id,
    )
    if unread_only:
        stmt = stmt.where(m.Notification.read_at.is_(None))
    if before is not None:
        stmt = stmt.where(m.Notification.created_at < before)
    items = list(
        await db.scalars(
            stmt.order_by(m.Notification.created_at.desc(), m.Notification.id.desc()).limit(limit)
        )
    )
    return Inbox(items=items, unread=await unread_count(db, actor))


async def unread_count(db: AsyncSession, actor: Principal) -> int:
    n = await db.scalar(
        select(func.count())
        .select_from(m.Notification)
        .where(
            m.Notification.user_id == actor.user_id,
            m.Notification.institution_id == actor.institution_id,
            m.Notification.read_at.is_(None),
        )
    )
    return int(n or 0)


async def mark_read(db: AsyncSession, actor: Principal, notification_id: uuid.UUID) -> None:
    note = await db.get(m.Notification, notification_id)
    # Someone else's notification looks exactly like a missing one.
    if note is None or note.user_id != actor.user_id:
        raise NotFound
    if note.read_at is None:
        note.read_at = now_utc()
        queue_event(db, actor.user_id, {"type": "notifications_read"})
    await db.commit()


async def mark_all_read(db: AsyncSession, actor: Principal) -> int:
    result = await db.execute(
        update(m.Notification)
        .where(
            m.Notification.user_id == actor.user_id,
            m.Notification.institution_id == actor.institution_id,
            m.Notification.read_at.is_(None),
        )
        .values(read_at=now_utc())
    )
    count = int(getattr(result, "rowcount", 0) or 0)
    if count:
        queue_event(db, actor.user_id, {"type": "notifications_read"})
    await db.commit()
    return count


# ---- external delivery ----------------------------------------------------------------------


@dataclasses.dataclass
class DispatchResult:
    sent: int = 0
    retried: int = 0
    failed: int = 0
    skipped: int = 0


def _skip(d: m.Delivery, code: str) -> None:
    d.status = DeliveryStatus.SKIPPED
    d.last_error = code


async def dispatch_due(
    session_factory: async_sessionmaker[AsyncSession],
    providers: Providers,
    *,
    now: dt.datetime | None = None,
    batch: int = 50,
) -> DispatchResult:
    """Send what is due. Safe to run from several processes: rows are claimed with
    ``FOR UPDATE SKIP LOCKED``, and a delivery is sent at most once per attempt."""
    now = now or now_utc()
    result = DispatchResult()
    async with session_factory() as db:
        due = list(
            await db.scalars(
                select(m.Delivery)
                .where(
                    m.Delivery.status == DeliveryStatus.PENDING,
                    m.Delivery.next_attempt_at <= now,
                )
                .order_by(m.Delivery.next_attempt_at)
                .limit(batch)
                .with_for_update(skip_locked=True)
            )
        )
        for d in due:
            user = await db.get(m.User, d.user_id)
            if user is None or user.status is not UserStatus.ACTIVE or user.deleted_at is not None:
                _skip(d, "recipient_inactive")
                result.skipped += 1
                continue
            provider = providers.get(d.channel)
            if provider is None:
                _skip(d, "no_provider")
                result.skipped += 1
                continue
            d.attempts += 1
            try:
                await provider.send(outbound(d.id, user.email))
            except DeliveryError as exc:
                d.last_error = exc.code
                if not exc.retryable or d.attempts >= MAX_ATTEMPTS:
                    d.status = DeliveryStatus.FAILED
                    result.failed += 1
                else:
                    d.next_attempt_at = now + BACKOFF[min(d.attempts, len(BACKOFF)) - 1]
                    result.retried += 1
                continue
            d.status = DeliveryStatus.SENT
            d.sent_at = now
            d.last_error = None
            result.sent += 1
        await db.commit()
    return result
