"""Declarative base, naming conventions and shared column mixins."""

import datetime as dt
import enum
import uuid
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, ForeignKeyConstraint, MetaData, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from app.infrastructure.db.ids import uuid7

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# One PostgreSQL schema per bounded context (see docs/DATABASE_DESIGN.md section 2).
SCHEMAS = (
    "iam",
    "org",
    "wellness",
    "therapy",
    "comm",
    "ai",
    "safety",
    "consent",
    "notify",
    "audit",
)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def enum_col(py_enum: type[enum.Enum], name: str) -> Enum:
    """VARCHAR + CHECK constraint (not a native PG enum) so values can evolve via migration."""
    return Enum(
        py_enum,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid7,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


def tenant_column(*, index: bool = True) -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        ForeignKey("org.institutions.id", ondelete="RESTRICT"),
        nullable=False,
        index=index,
    )


class TenantMixin:
    """Adds institution_id so row-level security can isolate tenants (policies come later).

    Tables that reference a student/therapist/user also declare a *composite* foreign key
    (``tenant_fk``) so ``institution_id`` can never disagree with the referenced row's tenant.
    """

    @declared_attr
    def institution_id(cls) -> Mapped[uuid.UUID]:  # noqa: N805
        return tenant_column()


def uuid_col(*, nullable: bool = False, **kw: Any) -> Mapped[Any]:
    """Plain UUID column; the foreign key is declared in ``__table_args__``."""
    return mapped_column(UUID(as_uuid=True), nullable=nullable, **kw)


def tenant_fk(
    column: str, target: str, *, ondelete: str, target_column: str = "user_id"
) -> ForeignKeyConstraint:
    """Composite FK ``(column, institution_id) -> target(target_column, institution_id)``.

    Guarantees the child row belongs to the same institution as the row it references.
    """
    return ForeignKeyConstraint(
        [column, "institution_id"],
        [f"{target}.{target_column}", f"{target}.institution_id"],
        ondelete=ondelete,
    )


class SoftDeleteMixin:
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def fk_uuid(target: str, *, ondelete: str, nullable: bool = False, **kw: Any) -> Mapped[Any]:
    """UUID foreign-key column with an explicit ON DELETE policy (no implicit defaults)."""
    return mapped_column(
        UUID(as_uuid=True), ForeignKey(target, ondelete=ondelete), nullable=nullable, **kw
    )
