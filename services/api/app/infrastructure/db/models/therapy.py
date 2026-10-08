"""therapy schema: Clinical-Confidential data (scheduling, sessions, therapist notes).

Kept in its own PostgreSQL schema so grants, row-level security, backups and audit can be
applied separately from general wellness data. Foreign keys into students/therapists use
RESTRICT: clinical records are retained under the retention policy, so a hard delete of a
user with therapy history is blocked and must go through the retention job.
"""

import datetime as dt
import uuid

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
from sqlalchemy.dialects.postgresql import UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import (
    Base,
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
    AppointmentStatus,
    SessionMode,
    TherapySessionStatus,
)


class TherapistAvailability(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "therapist_availability"
    __table_args__ = (
        tenant_fk("therapist_id", "org.therapists", ondelete="RESTRICT"),
        CheckConstraint("ends_at > starts_at", name="slot_valid"),
        UniqueConstraint("id", "therapist_id", name="uq_therapist_availability_id_therapist"),
        # A therapist cannot offer overlapping slots.
        ExcludeConstraint(
            ("therapist_id", "="),
            (text("tstzrange(starts_at, ends_at)"), "&&"),
            using="gist",
            name="ex_therapist_availability_no_overlap",
        ),
        Index("ix_therapist_availability_therapist_starts", "therapist_id", "starts_at"),
        {"schema": "therapy"},
    )

    therapist_id: Mapped[uuid.UUID] = uuid_col()
    starts_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    mode: Mapped[SessionMode] = mapped_column(
        enum_col(SessionMode, "availability_mode"),
        nullable=False,
        server_default=SessionMode.VIDEO.value,
    )


class Appointment(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "appointments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["availability_id", "therapist_id"],
            ["therapy.therapist_availability.id", "therapy.therapist_availability.therapist_id"],
            ondelete="RESTRICT",
            name="fk_appointments_availability_therapist",
        ),
        tenant_fk("therapist_id", "org.therapists", ondelete="RESTRICT"),
        tenant_fk("student_id", "org.students", ondelete="RESTRICT"),
        UniqueConstraint(
            "id",
            "student_id",
            "therapist_id",
            "institution_id",
            name="uq_appointments_id_parties_tenant",
        ),
        CheckConstraint("ends_at > starts_at", name="period_valid"),
        CheckConstraint(
            "(status = 'cancelled') = (cancelled_at IS NOT NULL)",
            name="cancelled_at_matches_status",
        ),
        CheckConstraint("student_id <> therapist_id", name="distinct_parties"),
        # One live appointment per availability slot.
        Index(
            "uq_appointments_live_slot",
            "availability_id",
            unique=True,
            postgresql_where=text(
                "status IN ('requested','confirmed') AND availability_id IS NOT NULL"
            ),
        ),
        # No double-booking of a therapist or of a student.
        ExcludeConstraint(
            ("therapist_id", "="),
            (text("tstzrange(starts_at, ends_at)"), "&&"),
            using="gist",
            where=text("status IN ('requested','confirmed')"),
            name="ex_appointments_therapist_no_overlap",
        ),
        ExcludeConstraint(
            ("student_id", "="),
            (text("tstzrange(starts_at, ends_at)"), "&&"),
            using="gist",
            where=text("status IN ('requested','confirmed')"),
            name="ex_appointments_student_no_overlap",
        ),
        # Backs the availability foreign key (the unique index above is partial).
        Index(
            "ix_appointments_availability_id",
            "availability_id",
            postgresql_where=text("availability_id IS NOT NULL"),
        ),
        Index("ix_appointments_student_starts", "student_id", text("starts_at DESC")),
        Index("ix_appointments_therapist_starts", "therapist_id", text("starts_at DESC")),
        Index(
            "ix_appointments_cancelled_by",
            "cancelled_by",
            postgresql_where=text("cancelled_by IS NOT NULL"),
        ),
        {"schema": "therapy"},
    )

    student_id: Mapped[uuid.UUID] = uuid_col()
    therapist_id: Mapped[uuid.UUID] = uuid_col()
    availability_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    starts_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    mode: Mapped[SessionMode] = mapped_column(
        enum_col(SessionMode, "appointment_mode"), nullable=False
    )
    status: Mapped[AppointmentStatus] = mapped_column(
        enum_col(AppointmentStatus, "appointment_status"),
        nullable=False,
        server_default=AppointmentStatus.REQUESTED.value,
    )
    reason: Mapped[str | None] = mapped_column(
        EncryptedText("therapy.appointments.reason"), nullable=True
    )
    cancelled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by: Mapped[uuid.UUID | None] = fk_uuid(
        "iam.users.id", ondelete="SET NULL", nullable=True
    )


class TherapySession(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """The delivered session for an appointment. Parties are denormalised and FK-checked."""

    __tablename__ = "therapy_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["appointment_id", "student_id", "therapist_id", "institution_id"],
            [
                "therapy.appointments.id",
                "therapy.appointments.student_id",
                "therapy.appointments.therapist_id",
                "therapy.appointments.institution_id",
            ],
            ondelete="RESTRICT",
            name="fk_therapy_sessions_appointment_parties",
        ),
        UniqueConstraint("appointment_id", name="uq_therapy_sessions_appointment_id"),
        UniqueConstraint(
            "id", "therapist_id", "institution_id", name="uq_therapy_sessions_id_therapist_tenant"
        ),
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="ended_after_started"),
        CheckConstraint(
            "(status = 'completed') = (ended_at IS NOT NULL)", name="ended_at_matches_status"
        ),
        Index("ix_therapy_sessions_student_id", "student_id"),
        Index("ix_therapy_sessions_therapist_started", "therapist_id", text("started_at DESC")),
        {"schema": "therapy"},
    )

    appointment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    therapist_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[TherapySessionStatus] = mapped_column(
        enum_col(TherapySessionStatus, "therapy_session_status"),
        nullable=False,
        server_default=TherapySessionStatus.SCHEDULED.value,
    )
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    video_meeting_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)


class TherapyNote(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Confidential clinical note. Body is encrypted; only the authoring therapist may read it.

    Versioned: an edit inserts a new row (version + 1); earlier versions are retained.
    The (session_id, author_id) pair is FK-checked, so only the session's own therapist
    can be the author.
    """

    __tablename__ = "therapy_notes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["session_id", "author_id", "institution_id"],
            [
                "therapy.therapy_sessions.id",
                "therapy.therapy_sessions.therapist_id",
                "therapy.therapy_sessions.institution_id",
            ],
            ondelete="RESTRICT",
            name="fk_therapy_notes_session_author",
        ),
        UniqueConstraint("session_id", "version", name="uq_therapy_notes_session_version"),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_therapy_notes_author_created", "author_id", text("created_at DESC")),
        {"schema": "therapy"},
    )

    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("1"))
    body: Mapped[str] = mapped_column(EncryptedText("therapy.therapy_notes.body"), nullable=False)
    locked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
