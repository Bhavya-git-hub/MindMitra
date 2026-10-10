"""Real-time events, published only after the transaction that caused them commits.

Use cases call ``queue_event`` while they work. Nothing leaves the process unless the database
commit succeeds, so a client is never told about a message or an appointment change that was
rolled back. Events carry identifiers and fixed words only, never what anyone wrote; the client
fetches content through the authorised REST API.

The broker is process-wide and set when the API starts. Without one (scripts, most tests) events
are dropped, which is harmless: they are a hint to refresh, not the record.
"""

import logging
import uuid
from typing import Any, Protocol

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

log = logging.getLogger("mindmitra.events")

_KEY = "mm_pending_events"

Event = dict[str, Any]


class EventBroker(Protocol):
    """Delivers an event to every open connection of one user. Must not block or raise."""

    def publish(self, user_id: uuid.UUID, payload: Event) -> None: ...


_broker: EventBroker | None = None


def set_broker(broker: EventBroker | None) -> None:
    global _broker
    _broker = broker


def get_broker() -> EventBroker | None:
    return _broker


def queue_event(db: AsyncSession | Session, user_id: uuid.UUID, payload: Event) -> None:
    sync = db.sync_session if isinstance(db, AsyncSession) else db
    sync.info.setdefault(_KEY, []).append((user_id, payload))


@event.listens_for(Session, "after_commit")
def _publish_after_commit(session: Session) -> None:
    pending: list[tuple[uuid.UUID, Event]] = session.info.pop(_KEY, [])
    broker = _broker
    if broker is None:
        return
    for user_id, payload in pending:
        try:
            broker.publish(user_id, payload)
        except Exception:  # a broken socket must never fail the request that committed
            log.exception("event publish failed type=%s", payload.get("type"))


@event.listens_for(Session, "after_rollback")
def _drop_after_rollback(session: Session) -> None:
    session.info.pop(_KEY, None)
