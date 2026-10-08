"""notify schema: in-app notifications and delivery tracking.

Payloads carry identifiers only. External channels (email/SMS/push) use content-free
templates, so no sensitive text is stored here.
"""

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, SmallInteger, String, text
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
from app.infrastructure.db.enums import NotificationChannel, NotificationPriority, NotificationType


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
