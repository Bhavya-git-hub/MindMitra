"""Append-only, hash-chained audit writer (per-institution chain).

Each row stores ``hash = SHA256(prev_hash || canonical_json(row fields))``. A per-institution
advisory lock serialises appends so the chain has no forks. Verification re-computes the
chain and reports the first broken row. Contents are metadata only: callers must never put
message bodies, notes or other clinical text into ``details``.
"""

import datetime as dt
import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.enums import AuditOutcome, UserRole
from app.infrastructure.db.ids import uuid7
from app.infrastructure.db.models.audit import AuditLog

# Audit details are metadata only. Content-bearing or credential-like keys are rejected so a
# careless caller cannot leak message bodies, notes or secrets into an append-only table.
FORBIDDEN_DETAIL_KEYS = frozenset(
    {
        "body", "content", "text", "message", "note", "notes", "title", "excerpt",
        "journal", "reason_text", "password", "password_hash", "token", "secret",
        "authorization", "cookie", "email", "phone", "full_name", "name",
    }
)  # fmt: skip
MAX_DETAIL_VALUE_LENGTH = 200


class AuditDetailsError(ValueError):
    """``details`` contains a forbidden key or an over-long string value."""


def validate_details(value: Any, path: str = "details") -> None:
    if isinstance(value, dict):
        for key, inner in value.items():
            if str(key).lower() in FORBIDDEN_DETAIL_KEYS:
                raise AuditDetailsError(f"{path}.{key}: key not allowed in audit details")
            validate_details(inner, f"{path}.{key}")
    elif isinstance(value, list | tuple):
        for i, inner in enumerate(value):
            validate_details(inner, f"{path}[{i}]")
    elif isinstance(value, str) and len(value) > MAX_DETAIL_VALUE_LENGTH:
        raise AuditDetailsError(f"{path}: string longer than {MAX_DETAIL_VALUE_LENGTH} characters")


def _canonical(fields: dict[str, Any]) -> str:
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(prev_hash: str | None, fields: dict[str, Any]) -> str:
    return hashlib.sha256(((prev_hash or "") + _canonical(fields)).encode("utf-8")).hexdigest()


def _hash_fields(row: AuditLog) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "institution_id": str(row.institution_id),
        "occurred_at": row.occurred_at.astimezone(dt.UTC).isoformat(),
        "actor_id": str(row.actor_id) if row.actor_id else None,
        "actor_role": row.actor_role.value if row.actor_role else None,
        "action": row.action,
        "resource_type": row.resource_type,
        "resource_id": str(row.resource_id) if row.resource_id else None,
        "subject_student_id": str(row.subject_student_id) if row.subject_student_id else None,
        "outcome": row.outcome.value,
        "reason": row.reason,
        "request_id": row.request_id,
        "ip_hash": row.ip_hash,
        "details": row.details,
    }


async def append_audit_event(
    session: AsyncSession,
    *,
    institution_id: uuid.UUID,
    action: str,
    outcome: AuditOutcome,
    actor_id: uuid.UUID | None = None,
    actor_role: UserRole | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    subject_student_id: uuid.UUID | None = None,
    reason: str | None = None,
    request_id: str | None = None,
    ip_hash: str | None = None,
    details: dict[str, Any] | None = None,
    occurred_at: dt.datetime | None = None,
) -> AuditLog:
    validate_details(details or {})
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"audit:{institution_id}"},
    )
    prev = (
        await session.execute(
            select(AuditLog.hash)
            .where(AuditLog.institution_id == institution_id)
            .order_by(AuditLog.seq.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    row = AuditLog(
        id=uuid7(),
        institution_id=institution_id,
        occurred_at=(occurred_at or dt.datetime.now(dt.UTC)).astimezone(dt.UTC),
        actor_id=actor_id,
        actor_role=actor_role,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        subject_student_id=subject_student_id,
        outcome=outcome,
        reason=reason,
        request_id=request_id,
        ip_hash=ip_hash,
        details=details or {},
        prev_hash=prev,
        hash="0" * 64,
    )
    row.hash = compute_hash(prev, _hash_fields(row))
    session.add(row)
    await session.flush()
    await session.refresh(row, ["seq"])  # server-assigned identity value
    return row


async def verify_chain(session: AsyncSession, institution_id: uuid.UUID) -> int | None:
    """Return the ``seq`` of the first row whose hash or link is wrong, or None if intact."""
    rows = (
        await session.execute(
            select(AuditLog).where(AuditLog.institution_id == institution_id).order_by(AuditLog.seq)
        )
    ).scalars()
    prev: str | None = None
    for row in rows:
        if row.prev_hash != prev or row.hash != compute_hash(prev, _hash_fields(row)):
            return row.seq
        prev = row.hash
    return None
