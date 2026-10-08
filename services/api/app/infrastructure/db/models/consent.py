"""consent schema: explicit, granular, revocable, versioned consent."""

import datetime as dt
import uuid

from sqlalchemy import CheckConstraint, DateTime, Index, String, func, text
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
from app.infrastructure.db.enums import ConsentScope


class Consent(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """One row per grant. Revoking sets ``revoked_at``; re-granting inserts a new row.

    History is therefore preserved, and the partial unique index guarantees at most one
    *active* grant per (user, scope).
    """

    __tablename__ = "consents"
    __table_args__ = (
        tenant_fk("user_id", "iam.users", ondelete="CASCADE", target_column="id"),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= granted_at", name="revoked_after_granted"
        ),
        CheckConstraint("btrim(policy_version) <> ''", name="policy_version_not_blank"),
        Index(
            "uq_consents_active_user_scope",
            "user_id",
            "scope",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index("ix_consents_user_scope_granted", "user_id", "scope", text("granted_at DESC")),
        {"schema": "consent"},
    )

    user_id: Mapped[uuid.UUID] = uuid_col()
    scope: Mapped[ConsentScope] = mapped_column(
        enum_col(ConsentScope, "consent_scope"), nullable=False
    )
    policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False, server_default="web")
    granted_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
