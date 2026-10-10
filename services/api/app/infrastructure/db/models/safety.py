"""safety schema: risk alerts that drive the human-support escalation workflow."""

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
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
    ReferralCategory,
    ReferralOutcome,
    ReferralStatus,
    ReferralUrgency,
    TeacherSupportStatus,
    TeacherSupportTopic,
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


def _course_link_fks(
    who: str, column: str, link: str, name: str, *, ondelete: str = "RESTRICT"
) -> ForeignKeyConstraint:
    """``(course_id, <who>_id, institution_id)`` must be a real teaching or enrolment link."""
    return ForeignKeyConstraint(
        ["course_id", column, "institution_id"],
        [f"org.{link}.course_id", f"org.{link}.{column}", f"org.{link}.institution_id"],
        ondelete=ondelete,
        name=name,
    )


class Referral(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """A teacher asks for a person from the wellbeing team to reach out to a student.

    Only a teacher of a course the student is enrolled in can raise one (both links are enforced
    by foreign keys). The factual note is encrypted. The teacher sees ``status`` and nothing
    else about what happens next; ``claimed_by`` and ``outcome`` are for therapists.
    """

    __tablename__ = "referrals"
    __table_args__ = (
        tenant_fk("teacher_id", "org.teachers", ondelete="RESTRICT"),
        tenant_fk("student_id", "org.students", ondelete="RESTRICT"),
        tenant_fk("claimed_by", "org.therapists", ondelete="RESTRICT"),
        _course_link_fks(
            "teacher", "teacher_id", "course_teachers", "fk_referrals_course_teacher_tenant"
        ),
        _course_link_fks(
            "student", "student_id", "course_enrollments", "fk_referrals_course_student_tenant"
        ),
        CheckConstraint(
            "(status = 'received') = (claimed_by IS NULL)", name="claimed_unless_received"
        ),
        CheckConstraint(
            "(status = 'closed') = (closed_at IS NOT NULL)", name="closed_at_matches_status"
        ),
        CheckConstraint("(status = 'closed') = (outcome IS NOT NULL)", name="outcome_when_closed"),
        # One live referral per teacher and student; a new one needs the last to be closed.
        Index(
            "uq_referrals_live_teacher_student",
            "teacher_id",
            "student_id",
            unique=True,
            postgresql_where=text("status <> 'closed'"),
        ),
        # The triage queue: live referrals, most urgent and oldest first.
        Index(
            "ix_referrals_open_queue",
            "institution_id",
            "urgency",
            "created_at",
            postgresql_where=text("status <> 'closed'"),
        ),
        Index("ix_referrals_student_id", "student_id"),
        Index("ix_referrals_teacher_id", "teacher_id"),
        Index("ix_referrals_course_id", "course_id"),
        Index(
            "ix_referrals_claimed_by", "claimed_by", postgresql_where=text("claimed_by IS NOT NULL")
        ),
        {"schema": "safety"},
    )

    teacher_id: Mapped[uuid.UUID] = uuid_col()
    student_id: Mapped[uuid.UUID] = uuid_col()
    course_id: Mapped[uuid.UUID] = uuid_col()
    category: Mapped[ReferralCategory] = mapped_column(
        enum_col(ReferralCategory, "referral_category"), nullable=False
    )
    urgency: Mapped[ReferralUrgency] = mapped_column(
        enum_col(ReferralUrgency, "referral_urgency"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(EncryptedText("safety.referrals.note"), nullable=True)
    status: Mapped[ReferralStatus] = mapped_column(
        enum_col(ReferralStatus, "referral_status"),
        nullable=False,
        server_default=ReferralStatus.RECEIVED.value,
    )
    claimed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    claimed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[ReferralOutcome | None] = mapped_column(
        enum_col(ReferralOutcome, "referral_outcome"), nullable=True
    )


class TeacherSupportRequest(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """A student explicitly asks one of their own teachers for help.

    The student chooses the teacher and course and writes the short message for that teacher, so
    the teacher seeing it is the student's own act. Nothing else about the student comes with it.
    """

    __tablename__ = "teacher_support_requests"
    __table_args__ = (
        tenant_fk("student_id", "org.students", ondelete="CASCADE"),
        tenant_fk("teacher_id", "org.teachers", ondelete="CASCADE"),
        # A request is a conversation, not a safety record: it goes when the class does.
        _course_link_fks(
            "teacher",
            "teacher_id",
            "course_teachers",
            "fk_teacher_support_course_teacher_tenant",
            ondelete="CASCADE",
        ),
        _course_link_fks(
            "student",
            "student_id",
            "course_enrollments",
            "fk_teacher_support_course_student_tenant",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status <> 'acknowledged' OR acknowledged_at IS NOT NULL",
            name="acknowledged_at_when_acknowledged",
        ),
        CheckConstraint(
            "(status IN ('closed','withdrawn')) = (closed_at IS NOT NULL)",
            name="closed_at_matches_status",
        ),
        Index(
            "uq_teacher_support_live",
            "student_id",
            "teacher_id",
            "course_id",
            unique=True,
            postgresql_where=text("status IN ('open','acknowledged')"),
        ),
        Index(
            "ix_teacher_support_teacher_status",
            "teacher_id",
            "status",
            text("created_at DESC"),
        ),
        Index("ix_teacher_support_student_created", "student_id", text("created_at DESC")),
        Index("ix_teacher_support_course_id", "course_id"),
        {"schema": "safety"},
    )

    student_id: Mapped[uuid.UUID] = uuid_col()
    teacher_id: Mapped[uuid.UUID] = uuid_col()
    course_id: Mapped[uuid.UUID] = uuid_col()
    topic: Mapped[TeacherSupportTopic] = mapped_column(
        enum_col(TeacherSupportTopic, "teacher_support_topic"), nullable=False
    )
    message: Mapped[str | None] = mapped_column(
        EncryptedText("safety.teacher_support_requests.message"), nullable=True
    )
    status: Mapped[TeacherSupportStatus] = mapped_column(
        enum_col(TeacherSupportStatus, "teacher_support_status"),
        nullable=False,
        server_default=TeacherSupportStatus.OPEN.value,
    )
    acknowledged_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
