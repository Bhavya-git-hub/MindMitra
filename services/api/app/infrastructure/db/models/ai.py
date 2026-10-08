"""ai schema: companion conversations and recommendations.

Conversations are visible only to the owning student. Messages are encrypted and expire
according to the student's retention choice (``expires_at``). Cascades from the student
so erasure removes them.
"""

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import (
    Base,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_col,
    fk_uuid,
)
from app.infrastructure.db.enums import (
    AIConversationStatus,
    AIMessageRole,
    RecommendationSource,
    RecommendationStatus,
)
from app.infrastructure.db.types import EncryptedText


class AIConversation(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "ai_conversations"
    __table_args__ = (
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="ended_after_started"),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > started_at", name="expires_after_start"
        ),
        Index("ix_ai_conversations_student_started", "student_id", text("started_at DESC")),
        Index(
            "ix_ai_conversations_expires_at",
            "expires_at",
            postgresql_where=text("expires_at IS NOT NULL"),
        ),
        {"schema": "ai"},
    )

    student_id: Mapped[uuid.UUID] = fk_uuid("org.students.user_id", ondelete="CASCADE")
    status: Mapped[AIConversationStatus] = mapped_column(
        enum_col(AIConversationStatus, "ai_conversation_status"),
        nullable=False,
        server_default=AIConversationStatus.ACTIVE.value,
    )
    model_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AIMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name="uq_ai_messages_conversation_seq"),
        CheckConstraint("seq >= 1", name="seq_positive"),
        CheckConstraint("token_count IS NULL OR token_count >= 0", name="token_count_non_negative"),
        {"schema": "ai"},
    )

    conversation_id: Mapped[uuid.UUID] = fk_uuid("ai.ai_conversations.id", ondelete="CASCADE")
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[AIMessageRole] = mapped_column(
        enum_col(AIMessageRole, "ai_message_role"), nullable=False
    )
    content: Mapped[str] = mapped_column(EncryptedText("ai.ai_messages.content"), nullable=False)
    crisis_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    safety_flags: Mapped[list[str]] = mapped_column(
        ARRAY(String(40)), nullable=False, server_default=text("'{}'")
    )
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Recommendation(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """A suggested resource/activity. Wording is supportive; never diagnostic."""

    __tablename__ = "recommendations"
    __table_args__ = (
        CheckConstraint("btrim(title) <> ''", name="title_not_blank"),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_range"
        ),
        CheckConstraint(
            "source <> 'model' OR model_version IS NOT NULL", name="model_source_has_version"
        ),
        Index("ix_recommendations_student_status", "student_id", "status"),
        Index("ix_recommendations_resource_id", "resource_id"),
        {"schema": "ai"},
    )

    student_id: Mapped[uuid.UUID] = fk_uuid("org.students.user_id", ondelete="CASCADE")
    resource_id: Mapped[uuid.UUID | None] = fk_uuid(
        "wellness.resources.id", ondelete="SET NULL", nullable=True
    )
    source: Mapped[RecommendationSource] = mapped_column(
        enum_col(RecommendationSource, "recommendation_source"), nullable=False
    )
    status: Mapped[RecommendationStatus] = mapped_column(
        enum_col(RecommendationStatus, "recommendation_status"),
        nullable=False,
        server_default=RecommendationStatus.PENDING.value,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
