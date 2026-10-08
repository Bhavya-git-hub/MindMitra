"""wellness schema: general (non-clinical) student wellbeing data.

Everything here is Sensitive but is *not* confidential therapy information; therapy
content lives in the separate ``therapy`` schema. Student deletion cascades here so the
right to erasure works for self-tracked data.
"""

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
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
)
from app.infrastructure.db.enums import GoalCategory, GoalStatus, ResourceType
from app.infrastructure.db.types import EncryptedText


class MoodEntry(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "mood_entries"
    __table_args__ = (
        CheckConstraint("mood_score BETWEEN 1 AND 5", name="mood_score_range"),
        CheckConstraint(
            "energy_level IS NULL OR energy_level BETWEEN 1 AND 5", name="energy_range"
        ),
        Index("ix_mood_entries_student_logged_at", "student_id", text("logged_at DESC")),
        {"schema": "wellness"},
    )

    student_id: Mapped[uuid.UUID] = fk_uuid("org.students.user_id", ondelete="CASCADE")
    mood_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    energy_level: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    emotions: Mapped[list[str]] = mapped_column(
        ARRAY(String(40)), nullable=False, server_default=text("'{}'")
    )
    note: Mapped[str | None] = mapped_column(
        EncryptedText("wellness.mood_entries.note"), nullable=True
    )
    logged_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WellnessAssessment(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Self-reported wellbeing questionnaire. A score is a snapshot, never a diagnosis."""

    __tablename__ = "wellness_assessments"
    __table_args__ = (
        CheckConstraint("max_score > 0", name="max_score_positive"),
        CheckConstraint("score >= 0 AND score <= max_score", name="score_within_max"),
        Index("ix_wellness_assessments_student_completed", "student_id", text("completed_at DESC")),
        {"schema": "wellness"},
    )

    student_id: Mapped[uuid.UUID] = fk_uuid("org.students.user_id", ondelete="CASCADE")
    instrument: Mapped[str] = mapped_column(String(60), nullable=False)
    instrument_version: Mapped[str] = mapped_column(String(20), nullable=False, server_default="1")
    score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    max_score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    responses: Mapped[dict[str, int]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    completed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class StressAssessment(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "stress_assessments"
    __table_args__ = (
        CheckConstraint("max_score > 0", name="max_score_positive"),
        CheckConstraint("score >= 0 AND score <= max_score", name="score_within_max"),
        CheckConstraint("perceived_stress_level BETWEEN 1 AND 5", name="stress_level_range"),
        Index("ix_stress_assessments_student_completed", "student_id", text("completed_at DESC")),
        {"schema": "wellness"},
    )

    student_id: Mapped[uuid.UUID] = fk_uuid("org.students.user_id", ondelete="CASCADE")
    scale: Mapped[str] = mapped_column(String(60), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    max_score: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    perceived_stress_level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    stressors: Mapped[list[str]] = mapped_column(
        ARRAY(String(60)), nullable=False, server_default=text("'{}'")
    )
    completed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SleepEntry(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "sleep_entries"
    __table_args__ = (
        UniqueConstraint("student_id", "sleep_date", name="uq_sleep_entries_student_date"),
        CheckConstraint("duration_minutes BETWEEN 0 AND 1440", name="duration_range"),
        CheckConstraint("quality BETWEEN 1 AND 5", name="quality_range"),
        CheckConstraint("wake_time > bedtime", name="wake_after_bedtime"),
        Index("ix_sleep_entries_student_date", "student_id", text("sleep_date DESC")),
        {"schema": "wellness"},
    )

    student_id: Mapped[uuid.UUID] = fk_uuid("org.students.user_id", ondelete="CASCADE")
    sleep_date: Mapped[dt.date] = mapped_column(Date, nullable=False)  # the morning you woke up
    bedtime: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    wake_time: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    quality: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class JournalEntry(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Private by default; shared with a therapist only via an explicit ``JournalShare``."""

    __tablename__ = "journal_entries"
    __table_args__ = (
        Index("ix_journal_entries_student_created", "student_id", text("created_at DESC")),
        {"schema": "wellness"},
    )

    student_id: Mapped[uuid.UUID] = fk_uuid("org.students.user_id", ondelete="CASCADE")
    title: Mapped[str | None] = mapped_column(
        EncryptedText("wellness.journal_entries.title"), nullable=True
    )
    body: Mapped[str] = mapped_column(
        EncryptedText("wellness.journal_entries.body"), nullable=False
    )
    mood_tag: Mapped[str | None] = mapped_column(String(40), nullable=True)


class JournalShare(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "journal_shares"
    __table_args__ = (
        UniqueConstraint("entry_id", "therapist_id", name="uq_journal_shares_entry_therapist"),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= shared_at", name="revoked_after_shared"
        ),
        Index("ix_journal_shares_therapist_id", "therapist_id"),
        {"schema": "wellness"},
    )

    entry_id: Mapped[uuid.UUID] = fk_uuid("wellness.journal_entries.id", ondelete="CASCADE")
    therapist_id: Mapped[uuid.UUID] = fk_uuid("org.therapists.user_id", ondelete="CASCADE")
    shared_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WellnessGoal(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "wellness_goals"
    __table_args__ = (
        CheckConstraint("btrim(title) <> ''", name="title_not_blank"),
        CheckConstraint(
            "target_date IS NULL OR target_date >= start_date", name="target_after_start"
        ),
        CheckConstraint("target_value IS NULL OR target_value > 0", name="target_positive"),
        CheckConstraint("current_value >= 0", name="current_non_negative"),
        CheckConstraint(
            "(status = 'completed') = (completed_at IS NOT NULL)",
            name="completed_at_matches_status",
        ),
        Index("ix_wellness_goals_student_status", "student_id", "status"),
        {"schema": "wellness"},
    )

    student_id: Mapped[uuid.UUID] = fk_uuid("org.students.user_id", ondelete="CASCADE")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[GoalCategory] = mapped_column(
        enum_col(GoalCategory, "goal_category"), nullable=False
    )
    status: Mapped[GoalStatus] = mapped_column(
        enum_col(GoalStatus, "goal_status"), nullable=False, server_default=GoalStatus.ACTIVE.value
    )
    target_value: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    current_value: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, server_default=text("0")
    )
    unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    start_date: Mapped[dt.date] = mapped_column(
        Date, nullable=False, server_default=func.current_date()
    )
    target_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Resource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Vetted self-help / service content. ``institution_id`` NULL means global."""

    __tablename__ = "resources"
    __table_args__ = (
        CheckConstraint("btrim(title) <> ''", name="title_not_blank"),
        CheckConstraint(
            "NOT is_published OR reviewed_at IS NOT NULL",
            name="published_requires_review",
        ),
        CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes > 0", name="duration_positive"
        ),
        Index("ix_resources_tags", "tags", postgresql_using="gin"),
        Index("ix_resources_published_type", "is_published", "resource_type"),
        Index(
            "ix_resources_reviewed_by",
            "reviewed_by",
            postgresql_where=text("reviewed_by IS NOT NULL"),
        ),
        {"schema": "wellness"},
    )

    institution_id: Mapped[uuid.UUID | None] = fk_uuid(
        "org.institutions.id", ondelete="CASCADE", nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resource_type: Mapped[ResourceType] = mapped_column(
        enum_col(ResourceType, "resource_type"), nullable=False
    )
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(40)), nullable=False, server_default=text("'{}'")
    )
    language: Mapped[str] = mapped_column(String(10), nullable=False, server_default="en")
    duration_minutes: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    reviewed_by: Mapped[uuid.UUID | None] = fk_uuid(
        "iam.users.id", ondelete="SET NULL", nullable=True
    )
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
