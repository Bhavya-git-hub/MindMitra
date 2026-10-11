"""ai schema: companion conversations, recommendations, and the student's feedback on them.

Conversations are visible only to the owning student. Messages are encrypted and expire
according to the student's retention choice (``expires_at``). Cascades from the student
so erasure removes them. Recommendation feedback and preferences are the student's own: only
they can read or change them, and no one else sees whether a suggestion was found helpful.
"""

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import (
    Base,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_col,
    fk_uuid,
    tenant_fk,
    uuid_col,
)
from app.infrastructure.db.column_types import EncryptedText
from app.infrastructure.db.enums import (
    AIConversationStatus,
    AIMessageRole,
    AIReplyKind,
    FeedbackRating,
    FeedbackReason,
    RecommendationSource,
    RecommendationStatus,
)


class AIConversation(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "ai_conversations"
    __table_args__ = (
        tenant_fk("student_id", "org.students", ondelete="CASCADE"),
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

    student_id: Mapped[uuid.UUID] = uuid_col()
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
    # Moves on every message; retention counts from here.
    last_message_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AIMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name="uq_ai_messages_conversation_seq"),
        CheckConstraint("seq >= 1", name="seq_positive"),
        CheckConstraint("token_count IS NULL OR token_count >= 0", name="token_count_non_negative"),
        CheckConstraint(
            "(role = 'assistant') = (reply_kind IS NOT NULL)", name="reply_kind_on_assistant"
        ),
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
    reply_kind: Mapped[AIReplyKind | None] = mapped_column(
        enum_col(AIReplyKind, "ai_reply_kind"), nullable=True
    )


class Recommendation(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """A suggested resource/activity. Wording is supportive; never diagnostic."""

    __tablename__ = "recommendations"
    __table_args__ = (
        tenant_fk("student_id", "org.students", ondelete="CASCADE"),
        CheckConstraint("btrim(title) <> ''", name="title_not_blank"),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_range"
        ),
        CheckConstraint(
            "source <> 'model' OR model_version IS NOT NULL", name="model_source_has_version"
        ),
        CheckConstraint("relevance IS NULL OR relevance BETWEEN 0 AND 1", name="relevance_range"),
        CheckConstraint(
            "problem_area IS NULL OR problem_area IN ('academic_burnout', 'career_anxiety', "
            "'social_isolation', 'sleep_disruption', 'stress', 'mood', 'engagement')",
            name="problem_area_known",
        ),
        # Lets feedback point at a recommendation of the same student and institution only.
        UniqueConstraint(
            "id", "student_id", "institution_id", name="uq_recommendations_link_tenant"
        ),
        Index("ix_recommendations_student_status", "student_id", "status"),
        Index("ix_recommendations_student_created", "student_id", "created_at"),
        Index("ix_recommendations_resource_id", "resource_id"),
        Index(
            "ix_recommendations_authored_by",
            "authored_by",
            postgresql_where=text("authored_by IS NOT NULL"),
        ),
        {"schema": "ai"},
    )

    student_id: Mapped[uuid.UUID] = uuid_col()
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
    # The therapist who made a `source = therapist` suggestion.
    authored_by: Mapped[uuid.UUID | None] = fk_uuid(
        "iam.users.id", ondelete="SET NULL", nullable=True
    )
    # Set by the recommendation engine (ADR 0012); empty on older and therapist-made rows.
    intervention_key: Mapped[str | None] = mapped_column(String(60), nullable=True)
    problem_area: Mapped[str | None] = mapped_column(String(30), nullable=True)
    relevance: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    # What the suggestion was when it was made, so feedback still teaches the engine after the
    # resource is edited or removed.
    resource_format: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(40)), nullable=False, server_default=text("'{}'")
    )
    # Why it was suggested, as numbers and signal names only (never text the student wrote).
    reasons: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    engine_version: Mapped[str | None] = mapped_column(String(80), nullable=True)


class RecommendationFeedback(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """A student's "helpful" or "not helpful" on one suggestion. One per suggestion; changing
    their mind replaces it. Used only to tune that student's own future suggestions."""

    __tablename__ = "recommendation_feedback"
    __table_args__ = (
        ForeignKeyConstraint(
            ["recommendation_id", "student_id", "institution_id"],
            [
                "ai.recommendations.id",
                "ai.recommendations.student_id",
                "ai.recommendations.institution_id",
            ],
            ondelete="CASCADE",
        ),
        UniqueConstraint("recommendation_id", name="uq_recommendation_feedback_recommendation"),
        CheckConstraint(
            "reason IS NULL OR rating = 'not_helpful'", name="reason_only_when_not_helpful"
        ),
        Index("ix_recommendation_feedback_student_updated", "student_id", "updated_at"),
        {"schema": "ai"},
    )

    student_id: Mapped[uuid.UUID] = uuid_col()
    recommendation_id: Mapped[uuid.UUID] = uuid_col()
    rating: Mapped[FeedbackRating] = mapped_column(
        enum_col(FeedbackRating, "feedback_rating"), nullable=False
    )
    reason: Mapped[FeedbackReason | None] = mapped_column(
        enum_col(FeedbackReason, "feedback_reason"), nullable=True
    )


class RecommendationPreference(TenantMixin, TimestampMixin, Base):
    """What a student wants from suggestions. One row per student, created when they first
    change a setting; no row means the defaults."""

    __tablename__ = "recommendation_preferences"
    __table_args__ = (
        tenant_fk("student_id", "org.students", ondelete="CASCADE"),
        CheckConstraint(
            "max_minutes IS NULL OR max_minutes BETWEEN 1 AND 180", name="max_minutes_range"
        ),
        {"schema": "ai"},
    )

    student_id: Mapped[uuid.UUID] = uuid_col(primary_key=True)
    preferred_formats: Mapped[list[str]] = mapped_column(
        ARRAY(String(20)), nullable=False, server_default=text("'{}'")
    )
    max_minutes: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    muted_areas: Mapped[list[str]] = mapped_column(
        ARRAY(String(30)), nullable=False, server_default=text("'{}'")
    )
    # Whether the wellness indicator models may be used to tune suggestions.
    use_indicators: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
