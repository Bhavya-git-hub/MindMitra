"""audit schema: append-only, hash-chained audit trail.

Audit rows deliberately hold *soft references* (no FKs) to users and resources so they
survive deletion of the people and records they describe. UPDATE, DELETE and TRUNCATE are
rejected by database triggers created in the migration.
"""

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Identity, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base, TenantMixin, UUIDPrimaryKeyMixin, enum_col
from app.infrastructure.db.enums import AuditOutcome, UserRole


class AuditLog(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint("btrim(action) <> ''", name="action_not_blank"),
        CheckConstraint("hash ~ '^[0-9a-f]{64}$'", name="hash_is_sha256_hex"),
        CheckConstraint(
            "prev_hash IS NULL OR prev_hash ~ '^[0-9a-f]{64}$'", name="prev_hash_is_sha256_hex"
        ),
        CheckConstraint("jsonb_typeof(details) = 'object'", name="details_is_object"),
        Index("ix_audit_logs_institution_seq", "institution_id", "seq", unique=True),
        Index("ix_audit_logs_institution_occurred", "institution_id", text("occurred_at DESC")),
        Index("ix_audit_logs_subject_occurred", "subject_student_id", text("occurred_at DESC")),
        Index("ix_audit_logs_actor_occurred", "actor_id", text("occurred_at DESC")),
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
        {"schema": "audit"},
    )

    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False)
    occurred_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_role: Mapped[UserRole | None] = mapped_column(
        enum_col(UserRole, "audit_actor_role"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)  # e.g. "therapy_note.read"
    resource_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    subject_student_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    outcome: Mapped[AuditOutcome] = mapped_column(
        enum_col(AuditOutcome, "audit_outcome"), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Metadata only (never message bodies, notes or other content).
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
