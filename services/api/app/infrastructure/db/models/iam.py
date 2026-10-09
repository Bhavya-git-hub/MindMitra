"""iam schema: accounts and credentials. Credentials live in a separate table."""

import datetime as dt
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.db.base import (
    Base,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_col,
    fk_uuid,
    tenant_column,
    tenant_fk,
    uuid_col,
)
from app.infrastructure.db.enums import (
    OneTimeTokenPurpose,
    SessionRevokeReason,
    UserRole,
    UserStatus,
)

_SHA256_HEX = "^[0-9a-f]{64}$"


class User(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        # Emails are stored lower-cased so a plain unique index is case-insensitive.
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint("position('@' in email) > 1", name="email_has_at"),
        CheckConstraint("btrim(full_name) <> ''", name="full_name_not_blank"),
        UniqueConstraint("institution_id", "email", name="uq_users_institution_email"),
        # Target of composite FKs: a profile row can only reference a user of its own role
        # and tenant.
        UniqueConstraint("id", "role", "institution_id", name="uq_users_id_role_institution"),
        # Target of composite tenant FKs (consents, notifications).
        UniqueConstraint("id", "institution_id", name="uq_users_id_institution"),
        Index("ix_users_institution_role_status", "institution_id", "role", "status"),
        {"schema": "iam"},
    )

    # Already the leading column of ix_users_institution_role_status, so no separate index.
    institution_id: Mapped[uuid.UUID] = tenant_column(index=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[UserRole] = mapped_column(enum_col(UserRole, "user_role"), nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        enum_col(UserStatus, "user_status"),
        nullable=False,
        server_default=UserStatus.INVITED.value,
    )
    last_login_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    credential: Mapped["Credential | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True, uselist=False
    )


class Credential(TimestampMixin, Base):
    """Password hash only (Argon2id). No plaintext, no reversible encoding, ever."""

    __tablename__ = "credentials"
    __table_args__ = (
        CheckConstraint("password_hash LIKE '$argon2id$%'", name="password_hash_is_argon2id"),
        CheckConstraint("failed_attempts >= 0", name="failed_attempts_non_negative"),
        {"schema": "iam"},
    )

    user_id: Mapped[uuid.UUID] = fk_uuid("iam.users.id", ondelete="CASCADE", primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    password_changed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    failed_attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    locked_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="credential")


class AuthSession(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """One signed-in device. Its refresh tokens form a rotation family; revoking the session
    revokes every token in it and invalidates its access tokens on their next use."""

    __tablename__ = "auth_sessions"
    __table_args__ = (
        tenant_fk("user_id", "iam.users", ondelete="CASCADE", target_column="id"),
        CheckConstraint("absolute_expires_at > created_at", name="expiry_after_creation"),
        CheckConstraint(
            "(revoked_at IS NULL) = (revoked_reason IS NULL)", name="revoked_reason_matches"
        ),
        CheckConstraint(f"ip_hash IS NULL OR ip_hash ~ '{_SHA256_HEX}'", name="ip_hash_format"),
        Index("ix_auth_sessions_user_id", "user_id"),
        {"schema": "iam"},
    )

    user_id: Mapped[uuid.UUID] = uuid_col()
    absolute_expires_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_seen_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[SessionRevokeReason | None] = mapped_column(
        enum_col(SessionRevokeReason, "session_revoke_reason"), nullable=True
    )
    # Keyed hash of the client IP (never the raw address).
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class RefreshToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Opaque refresh token, stored only as a SHA-256 hash. Single use: rotation marks it used,
    and presenting a used token again revokes the whole session (reuse detection)."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
        CheckConstraint(f"token_hash ~ '{_SHA256_HEX}'", name="token_hash_format"),
        CheckConstraint(f"csrf_hash ~ '{_SHA256_HEX}'", name="csrf_hash_format"),
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        Index("ix_refresh_tokens_session_id", "session_id"),
        {"schema": "iam"},
    )

    session_id: Mapped[uuid.UUID] = fk_uuid("iam.auth_sessions.id", ondelete="CASCADE")
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Hash of the CSRF token issued with this refresh token (double-submit, see api/auth).
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OneTimeToken(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Single-use, short-lived token for password reset, account setup or email verification.
    Only the SHA-256 hash is stored; the token itself is delivered out of band."""

    __tablename__ = "one_time_tokens"
    __table_args__ = (
        tenant_fk("user_id", "iam.users", ondelete="CASCADE", target_column="id"),
        UniqueConstraint("token_hash", name="uq_one_time_tokens_token_hash"),
        CheckConstraint(f"token_hash ~ '{_SHA256_HEX}'", name="token_hash_format"),
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        Index("ix_one_time_tokens_user_purpose", "user_id", "purpose"),
        {"schema": "iam"},
    )

    user_id: Mapped[uuid.UUID] = uuid_col()
    purpose: Mapped[OneTimeTokenPurpose] = mapped_column(
        enum_col(OneTimeTokenPurpose, "one_time_token_purpose"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
