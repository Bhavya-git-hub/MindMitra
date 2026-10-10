"""In-process fan-out of real-time events to a user's open WebSocket connections.

One ``Hub`` per API process. That is enough for a single API instance; several instances need a
shared broker (for example Redis pub/sub) behind the same ``EventBroker`` interface so an event
raised on one instance reaches a socket held by another. Until then, clients also refresh on
reconnect and when the page regains focus, so a missed event costs freshness, not data.
"""

import asyncio
import uuid
from collections import defaultdict

from app.infrastructure.events import Event

QUEUE_SIZE = 100


class Connection:
    """One open socket's outbox. A consumer that falls behind is disconnected, not blocked."""

    def __init__(self, user_id: uuid.UUID) -> None:
        self.user_id = user_id
        self.queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self.overflowed = False

    def offer(self, payload: Event) -> None:
        try:
            self.queue.put_nowait(payload)
        except asyncio.QueueFull:
            self.overflowed = True


class Hub:
    def __init__(self, *, max_per_user: int = 5) -> None:
        self.max_per_user = max_per_user
        self._by_user: dict[uuid.UUID, list[Connection]] = defaultdict(list)

    def register(self, user_id: uuid.UUID) -> Connection | None:
        """A new connection, or None when the user already has the maximum open."""
        conns = self._by_user[user_id]
        if len(conns) >= self.max_per_user:
            return None
        conn = Connection(user_id)
        conns.append(conn)
        return conn

    def unregister(self, conn: Connection) -> None:
        conns = self._by_user.get(conn.user_id)
        if not conns:
            return
        if conn in conns:
            conns.remove(conn)
        if not conns:
            del self._by_user[conn.user_id]

    def publish(self, user_id: uuid.UUID, payload: Event) -> None:
        for conn in list(self._by_user.get(user_id, ())):
            conn.offer(payload)

    def connection_count(self, user_id: uuid.UUID) -> int:
        return len(self._by_user.get(user_id, ()))
