"""safety schema: risk alerts that drive the human-support escalation workflow."""

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import (
    Base,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_col,
    fk_uuid,
)
from app.infrastructure.db.enums import (
    AlertCategory,
    AlertDetector,
    AlertSeverity,
    AlertSource,
    AlertStatus,
)
from app.infrastructure.db.types import EncryptedText


class RiskAlert(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """A signal that a student may need human support.

    This is an escalation record, not a diagnosis: categories contain no clinical labels,
    ``requires_human`` is always true, and only a minimal encrypted excerpt is stored.
    """

    __tablename__ = "risk_alerts"
    __table_args__ = (
        CheckConstraint("requires_human", name="always_requires_human"),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_range"
        ),
        CheckConstraint(
            "(status IN ('resolved','dismissed')) = (resolved_at IS NOT NULL)",
            name="resolved_at_matches_status",
        ),
        CheckConstraint(
            "status = 'open' OR status = 'dismissed' OR acknowledged_at IS NOT NULL",
            name="acknowledged_before_progress",
        ),
        CheckConstraint(
            "severity NOT IN ('high','imminent') OR sla_ack_due_at IS NOT NULL",
            name="high_severity_has_sla",
        ),
        CheckConstraint("(source_type IS NULL) = (source_id IS NULL)", name="source_ref_complete"),
        # The on-call queue: open alerts ordered by SLA deadline.
        Index(
            "ix_risk_alerts_open_sla",
            "institution_id",
            "sla_ack_due_at",
            postgresql_where=text("status IN ('open','escalated')"),
        ),
        Index("ix_risk_alerts_student_created", "student_id", text("created_at DESC")),
        Index("ix_risk_alerts_assigned_status", "assigned_to", "status"),
        {"schema": "safety"},
    )

    # RESTRICT: clinical/safety records follow the retention policy, not cascade deletion.
    student_id: Mapped[uuid.UUID] = fk_uuid("org.students.user_id", ondelete="RESTRICT")
    assigned_to: Mapped[uuid.UUID | None] = fk_uuid(
        "org.therapists.user_id", ondelete="SET NULL", nullable=True
    )
    source: Mapped[AlertSource] = mapped_column(
        enum_col(AlertSource, "alert_source"), nullable=False
    )
    source_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    detector: Mapped[AlertDetector] = mapped_column(
        enum_col(AlertDetector, "alert_detector"), nullable=False
    )
    category: Mapped[AlertCategory] = mapped_column(
        enum_col(AlertCategory, "alert_category"), nullable=False
    )
    severity: Mapped[AlertSeverity] = mapped_column(
        enum_col(AlertSeverity, "alert_severity"), nullable=False
    )
    status: Mapped[AlertStatus] = mapped_column(
        enum_col(AlertStatus, "alert_status"),
        nullable=False,
        server_default=AlertStatus.OPEN.value,
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    requires_human: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    excerpt: Mapped[str | None] = mapped_column(
        EncryptedText("safety.risk_alerts.excerpt"), nullable=True
    )
    sla_ack_due_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acknowledged_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(60), nullable=True)
