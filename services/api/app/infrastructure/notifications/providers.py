"""Delivery providers for notifications that leave the app (e-mail now, push or SMS later).

The application depends on ``NotificationProvider`` only. Adding a channel means writing a
provider for it and registering it in ``build_providers``; nothing else changes. Every message
is the same content-free template: it says there is something new and never what it is, because
an e-mail inbox or a lock screen may be read by someone else.
"""

import dataclasses
import logging
import uuid
from collections.abc import Mapping
from typing import Final, Protocol

from app.infrastructure.db.enums import NotificationChannel

log = logging.getLogger("mindmitra.notifications")

SUBJECT: Final = "You have something new in MindMitra"
TEXT: Final = (
    "Something new is waiting for you in MindMitra. Sign in to see it.\n\n"
    "If you need urgent help, use the Get help button in the app or contact your local "
    "emergency number."
)


@dataclasses.dataclass(frozen=True)
class OutboundMessage:
    delivery_id: uuid.UUID
    to: str
    subject: str
    text: str


class DeliveryError(Exception):
    """A provider could not send. ``code`` is short and machine-readable (it is stored)."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code[:40]
        self.retryable = retryable


class NotificationProvider(Protocol):
    channel: NotificationChannel

    async def send(self, message: OutboundMessage) -> None:
        """Send or raise ``DeliveryError``. Must not log the address or the text."""


def outbound(delivery_id: uuid.UUID, to: str) -> OutboundMessage:
    return OutboundMessage(delivery_id=delivery_id, to=to, subject=SUBJECT, text=TEXT)


class LoggingEmailProvider:
    """Development only: records that a delivery happened, with ids and nothing else."""

    channel = NotificationChannel.EMAIL

    async def send(self, message: OutboundMessage) -> None:
        log.info("email delivery %s handed to the log provider", message.delivery_id)


class InMemoryProvider:
    """Keeps messages in memory. Tests use it, and can make it fail on demand."""

    def __init__(self, channel: NotificationChannel = NotificationChannel.EMAIL) -> None:
        self.channel = channel
        self.sent: list[OutboundMessage] = []
        self.fail_with: DeliveryError | None = None

    async def send(self, message: OutboundMessage) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append(message)


Providers = Mapping[NotificationChannel, NotificationProvider]


def build_providers(email: str) -> dict[NotificationChannel, NotificationProvider]:
    providers: dict[NotificationChannel, NotificationProvider] = {}
    if email == "log":
        providers[NotificationChannel.EMAIL] = LoggingEmailProvider()
    return providers
