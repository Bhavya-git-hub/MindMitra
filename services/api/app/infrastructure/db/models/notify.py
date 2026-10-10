"""notify schema: in-app notifications and delivery tracking.

Payloads carry identifiers only. External channels (email/SMS/push) use content-free
templates, so no sensitive text is stored here.
"""

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import (
    Base,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_col,
    tenant_fk,
    uuid_col,
)
from app.infrastructure.db.enums import (
    DeliveryStatus,
    NotificationChannel,
    NotificationPriority,
    NotificationType,
)


class Notification(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        tenant_fk("user_id", "iam.users", ondelete="CASCADE", target_column="id"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_is_object"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        CheckConstraint("read_at IS NULL OR read_at >= created_at", name="read_after_created"),
        Index(
            "ix_notifications_user_unread",
            "user_id",
            text("created_at DESC"),
            postgresql_where=text("read_at IS NULL"),
        ),
        Index("ix_notifications_user_created", "user_id", text("created_at DESC")),
        UniqueConstraint("id", "institution_id", name="uq_notifications_id_tenant"),
        {"schema": "notify"},
    )

    user_id: Mapped[uuid.UUID] = uuid_col()
    type: Mapped[NotificationType] = mapped_column(
        enum_col(NotificationType, "notification_type"), nullable=False
    )
    priority: Mapped[NotificationPriority] = mapped_column(
        enum_col(NotificationPriority, "notification_priority"),
        nullable=False,
        server_default=NotificationPriority.NORMAL.value,
    )
    channel: Mapped[NotificationChannel] = mapped_column(
        enum_col(NotificationChannel, "notification_channel"),
        nullable=False,
        server_default=NotificationChannel.IN_APP.value,
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Delivery(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """One attempt-tracked delivery of a notification over an external channel.

    Holds no address and no text: the dispatcher looks the address up when it sends, and the
    message is a fixed, content-free template for the notification type.
    """

    __tablename__ = "deliveries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["notification_id", "institution_id"],
            ["notify.notifications.id", "notify.notifications.institution_id"],
            ondelete="CASCADE",
            name="fk_deliveries_notification_tenant",
        ),
        tenant_fk("user_id", "iam.users", ondelete="CASCADE", target_column="id"),
        UniqueConstraint("notification_id", "channel", name="uq_deliveries_notification_channel"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        CheckConstraint("(status = 'sent') = (sent_at IS NOT NULL)", name="sent_at_matches_status"),
        Index(
            "ix_deliveries_due",
            "next_attempt_at",
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_deliveries_user_id", "user_id"),
        {"schema": "notify"},
    )

    notification_id: Mapped[uuid.UUID] = uuid_col()
    user_id: Mapped[uuid.UUID] = uuid_col()
    channel: Mapped[NotificationChannel] = mapped_column(
        enum_col(NotificationChannel, "delivery_channel"), nullable=False
    )
    status: Mapped[DeliveryStatus] = mapped_column(
        enum_col(DeliveryStatus, "delivery_status"),
        nullable=False,
        server_default=DeliveryStatus.PENDING.value,
    )
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    next_attempt_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # A short machine code (for example "no_provider", "timeout"), never provider text.
    last_error: Mapped[str | None] = mapped_column(String(40), nullable=True)


class AppointmentReminder(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Records that the reminders for one appointment time and offset were sent, so the
    scheduler never sends them twice. Moving the appointment changes ``starts_at``, so the
    new time gets its own reminders."""

    __tablename__ = "appointment_reminders"
    __table_args__ = (
        ForeignKeyConstraint(
            ["appointment_id", "institution_id"],
            ["therapy.appointments.id", "therapy.appointments.institution_id"],
            ondelete="CASCADE",
            name="fk_appointment_reminders_appointment_tenant",
        ),
        UniqueConstraint(
            "appointment_id",
            "starts_at",
            "offset_hours",
            name="uq_appointment_reminders_once",
        ),
        CheckConstraint("offset_hours BETWEEN 1 AND 168", name="offset_hours_range"),
        {"schema": "notify"},
    )

    appointment_id: Mapped[uuid.UUID] = uuid_col()
    starts_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    offset_hours: Mapped[int] = mapped_column(SmallInteger, nullable=False)
