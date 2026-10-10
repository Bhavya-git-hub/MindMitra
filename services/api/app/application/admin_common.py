"""Pieces shared by the administrator use cases."""

import uuid
from typing import Any

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.auth.policies import Principal
from app.infrastructure.db.audit import append_audit_event
from app.infrastructure.db.enums import AuditOutcome, UserRole

MAX_LIMIT = 200


def like(term: str) -> str:
    """A ``LIKE`` pattern for a user-typed search term; use with ``escape=LIKE_ESCAPE``."""
    cleaned = term.strip()[:80].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{cleaned}%"


LIKE_ESCAPE = "\\"


async def count(db: AsyncSession, stmt: Select[int]) -> int:
    return await db.scalar(stmt) or 0


async def audit(
    db: AsyncSession,
    actor: Principal,
    action: str,
    *,
    resource_type: str,
    resource_id: uuid.UUID | None = None,
    subject_student_id: uuid.UUID | None = None,
    **details: Any,
) -> None:
    """Record an administrator action. ``details`` is metadata only (ids, counts, codes)."""
    await append_audit_event(
        db,
        institution_id=actor.institution_id,
        actor_id=actor.user_id,
        actor_role=UserRole.ADMINISTRATOR,
        action=action,
        outcome=AuditOutcome.ALLOWED,
        resource_type=resource_type,
        resource_id=resource_id,
        subject_student_id=subject_student_id,
        details=details,
    )
