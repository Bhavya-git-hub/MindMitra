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
    SmallInteger,
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
    tenant_fk,
    uuid_col,
)
from app.infrastructure.db.column_types import EncryptedText
from app.infrastructure.db.enums import (
    AlertCategory,
    AlertDetector,
    AlertSeverity,
    AlertSource,
    AlertStatus,
    CrisisContactKind,
)


class RiskAlert(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """A signal that a student may need human support.

    This is an escalation record, not a diagnosis: categories contain no clinical labels,
    ``requires_human`` is always true, and only a minimal encrypted excerpt is stored.
    """

    __tablename__ = "risk_alerts"
    __table_args__ = (
        # RESTRICT: safety records follow the retention policy, not cascade deletion.
        tenant_fk("student_id", "org.students", ondelete="RESTRICT"),
        tenant_fk("assigned_to", "org.therapists", ondelete="RESTRICT"),
        CheckConstraint("requires_human", name="always_requires_human"),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_range"
        ),
        CheckConstraint(
            "(status IN ('resolved','dismissed')) = (resolved_at IS NOT NULL)",
            name="resolved_at_matches_status",
        ),
        CheckConstraint(
            "status IN ('open','escalated','dismissed') OR acknowledged_at IS NOT NULL",
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

    student_id: Mapped[uuid.UUID] = uuid_col()
    assigned_to: Mapped[uuid.UUID | None] = uuid_col(nullable=True)
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


class CrisisContact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A place to get help right now: emergency number, helpline or campus service.

    ``institution_id`` NULL means the contact applies to every institution (national lines).
    Shown to students on the emergency page; kept in the database so an institution can keep
    its own contacts current without a code change.
    """

    __tablename__ = "crisis_contacts"
    __table_args__ = (
        CheckConstraint("btrim(label) <> ''", name="label_not_blank"),
        CheckConstraint(
            "phone IS NOT NULL OR url IS NOT NULL OR description IS NOT NULL",
            name="has_a_way_to_reach",
        ),
        Index("ix_crisis_contacts_institution_active", "institution_id", "is_active", "sort_order"),
        {"schema": "safety"},
    )

    institution_id: Mapped[uuid.UUID | None] = fk_uuid(
        "org.institutions.id", ondelete="CASCADE", nullable=True
    )
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[CrisisContactKind] = mapped_column(
        enum_col(CrisisContactKind, "crisis_contact_kind"), nullable=False
    )
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    hours: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sort_order: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("100")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
