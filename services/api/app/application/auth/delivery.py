"""Out-of-band delivery of one-time tokens (password reset, account setup, verification).

The application depends on the ``TokenDelivery`` protocol only. Development and tests use
``InMemoryTokenOutbox``; a real e-mail sender is wired in with the notifications phase, and
the API refuses to start in staging/production without one (see ``app/api/main.py``).
Tokens are never logged.
"""

import dataclasses
import uuid
from typing import Protocol

from app.infrastructure.db.enums import OneTimeTokenPurpose


@dataclasses.dataclass(frozen=True)
class DeliveredToken:
    user_id: uuid.UUID
    email: str
    purpose: OneTimeTokenPurpose
    token: str


class TokenDelivery(Protocol):
    async def send(
        self, *, user_id: uuid.UUID, email: str, purpose: OneTimeTokenPurpose, token: str
    ) -> None: ...


class InMemoryTokenOutbox:
    """Keeps delivered tokens in memory. For development and tests only."""

    def __init__(self) -> None:
        self.sent: list[DeliveredToken] = []

    async def send(
        self, *, user_id: uuid.UUID, email: str, purpose: OneTimeTokenPurpose, token: str
    ) -> None:
        self.sent.append(DeliveredToken(user_id, email, purpose, token))

    def latest(self, email: str, purpose: OneTimeTokenPurpose) -> str | None:
        for item in reversed(self.sent):
            if item.email == email and item.purpose is purpose:
                return item.token
        return None
