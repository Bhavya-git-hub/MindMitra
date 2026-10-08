"""comm schema: secure student <-> therapist messaging."""

import datetime as dt
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import (
    Base,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    tenant_fk,
)
from app.infrastructure.db.column_types import EncryptedText


class Message(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """A message in the conversation between one student and one of their therapists.

    The conversation is identified by (student_id, therapist_id); the sender must be one
    of the two parties. Body is encrypted. Retained under the clinical retention policy,
    so foreign keys use RESTRICT.
    """

    __tablename__ = "messages"
    __table_args__ = (
        tenant_fk("student_id", "org.students", ondelete="RESTRICT"),
        tenant_fk("therapist_id", "org.therapists", ondelete="RESTRICT"),
        ForeignKeyConstraint(
            ["sender_id"],
            ["iam.users.id"],
            ondelete="RESTRICT",
            name="fk_messages_sender_id_users",
        ),
        CheckConstraint("sender_id IN (student_id, therapist_id)", name="sender_is_participant"),
        CheckConstraint("read_at IS NULL OR read_at >= created_at", name="read_after_created"),
        UniqueConstraint("sender_id", "client_msg_id", name="uq_messages_sender_client_msg"),
        Index("ix_messages_conversation_created", "student_id", "therapist_id", "created_at"),
        # Backs the therapist foreign key (ix_messages_unread below is partial).
        Index("ix_messages_therapist_id", "therapist_id"),
        Index(
            "ix_messages_unread",
            "therapist_id",
            "student_id",
            postgresql_where=text("read_at IS NULL"),
        ),
        {"schema": "comm"},
    )

    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    therapist_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    sender_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    body: Mapped[str] = mapped_column(EncryptedText("comm.messages.body"), nullable=False)
    # Client-generated id: makes retries idempotent.
    client_msg_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    read_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    crisis_checked_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
