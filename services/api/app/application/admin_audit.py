"""The audit log as administrators see it: who did what and when, never what was said.

Rows carry actions, outcomes and identifiers only (``append_audit_event`` rejects content-bearing
keys), so showing them does not widen what an administrator can learn about a student. Reading the
log is itself recorded, so a reviewer of the log can be reviewed too.
"""

import csv
import dataclasses
import datetime as dt
import io
import uuid

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.admin_common import MAX_LIMIT, audit
from app.application.errors import InvalidInput
from app.domain.auth.policies import Principal
from app.infrastructure.db import models as m
from app.infrastructure.db.audit import verify_chain
from app.infrastructure.db.enums import AuditOutcome, UserRole

EXPORT_LIMIT = 5000
MAX_RANGE = dt.timedelta(days=366)


@dataclasses.dataclass(frozen=True)
class AuditFilter:
    action: str | None = None
    outcome: AuditOutcome | None = None
    actor_id: uuid.UUID | None = None
    resource_type: str | None = None
    since: dt.datetime | None = None
    until: dt.datetime | None = None


def _select(actor: Principal, f: AuditFilter) -> Select[m.AuditLog]:
    if f.since and f.until and f.until - f.since > MAX_RANGE:
        raise InvalidInput("Please choose a range of a year or less.")
    stmt = select(m.AuditLog).where(m.AuditLog.institution_id == actor.institution_id)
    if f.action:
        # A trailing dot means "this family" (for example "user." covers every user action).
        if f.action.endswith("."):
            stmt = stmt.where(m.AuditLog.action.startswith(f.action, autoescape=True))
        else:
            stmt = stmt.where(m.AuditLog.action == f.action)
    if f.outcome is not None:
        stmt = stmt.where(m.AuditLog.outcome == f.outcome)
    if f.actor_id is not None:
        stmt = stmt.where(m.AuditLog.actor_id == f.actor_id)
    if f.resource_type:
        stmt = stmt.where(m.AuditLog.resource_type == f.resource_type)
    if f.since is not None:
        stmt = stmt.where(m.AuditLog.occurred_at >= f.since)
    if f.until is not None:
        stmt = stmt.where(m.AuditLog.occurred_at < f.until)
    return stmt


async def list_events(
    db: AsyncSession,
    actor: Principal,
    f: AuditFilter,
    *,
    before_seq: int | None,
    limit: int,
) -> list[m.AuditLog]:
    stmt = _select(actor, f)
    if before_seq is not None:
        stmt = stmt.where(m.AuditLog.seq < before_seq)
    rows = list(await db.scalars(stmt.order_by(m.AuditLog.seq.desc()).limit(min(limit, MAX_LIMIT))))
    if before_seq is None:  # the first page is a "look", later pages are the same look
        await audit(
            db,
            actor,
            "audit.read",
            resource_type="audit_log",
            has_filter=any(dataclasses.astuple(f)),
        )
        await db.commit()
    return rows


async def actions(db: AsyncSession, actor: Principal) -> list[str]:
    """The distinct action names recorded for this institution, for the filter menu."""
    rows = await db.scalars(
        select(m.AuditLog.action)
        .where(m.AuditLog.institution_id == actor.institution_id)
        .group_by(m.AuditLog.action)
        .order_by(m.AuditLog.action)
        .limit(500)
    )
    return list(rows)


@dataclasses.dataclass(frozen=True)
class ChainStatus:
    intact: bool
    first_bad_seq: int | None
    events: int
    checked_at: dt.datetime


async def verify(db: AsyncSession, actor: Principal) -> ChainStatus:
    bad = await verify_chain(db, actor.institution_id)
    events = (
        await db.scalar(
            select(func.count())
            .select_from(m.AuditLog)
            .where(m.AuditLog.institution_id == actor.institution_id)
        )
        or 0
    )
    await audit(
        db,
        actor,
        "audit.verify",
        resource_type="audit_log",
        intact=bad is None,
        events=events,
    )
    await db.commit()
    return ChainStatus(bad is None, bad, events, dt.datetime.now(dt.UTC))


_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: object) -> str:
    text = "" if value is None else str(value)
    # Spreadsheet programs run cells that start like a formula; keep exports inert.
    return "'" + text if text.startswith(_CSV_FORMULA_PREFIXES) else text


async def export_csv(db: AsyncSession, actor: Principal, f: AuditFilter) -> str:
    rows = list(
        await db.scalars(_select(actor, f).order_by(m.AuditLog.seq.desc()).limit(EXPORT_LIMIT))
    )
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        ["seq", "occurred_at", "actor_id", "actor_role", "action", "outcome", "resource_type",
         "resource_id", "subject_student_id", "reason"]
    )  # fmt: skip
    for r in rows:
        writer.writerow(
            _cell(v)
            for v in (
                r.seq,
                r.occurred_at.isoformat(),
                r.actor_id,
                r.actor_role.value if isinstance(r.actor_role, UserRole) else None,
                r.action,
                r.outcome.value,
                r.resource_type,
                r.resource_id,
                r.subject_student_id,
                r.reason,
            )
        )
    await audit(
        db,
        actor,
        "audit.export",
        resource_type="audit_log",
        rows=len(rows),
        truncated=len(rows) == EXPORT_LIMIT,
    )
    await db.commit()
    return out.getvalue()
