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
)
from app.infrastructure.db.enums import UserRole, UserStatus


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
        Index("ix_users_institution_role_status", "institution_id", "role", "status"),
        {"schema": "iam"},
    )

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
