"""The audit log as administrators see it: who did what and when, never what was said.

Rows carry actions, outcomes and identifiers only (``append_audit_event`` rejects content-bearing
keys). Identifiers alone can still tell a story, though: "therapist T read student S" is a care
relationship, and "student S created a safety event" is a crisis. So on care records (the
``CARE_RECORDS`` resource types) an administrator sees the action, when, the outcome and the staff
member, but no student, record id or details, and a student's own actions on care records are not
listed at all (ADR 0008 as amended by the 2026-10 security audit). Reading the log is itself
recorded, so a reviewer of the log can be reviewed too.
"""

import csv
import dataclasses
import datetime as dt
import io
import uuid
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.admin_common import MAX_LIMIT, audit
from app.application.errors import InvalidInput
from app.domain.auth.policies import Principal
from app.infrastructure.db import models as m
from app.infrastructure.db.audit import verify_chain
from app.infrastructure.db.enums import AuditOutcome, UserRole

EXPORT_LIMIT = 5000
MAX_RANGE = dt.timedelta(days=366)

# Resource types whose rows describe someone's care, wellbeing or safety. The full rows stay in
# the log (and in the hash chain) for investigations; only the administrator's view is reduced.
CARE_RECORDS = frozenset(
    {
        "ai_conversation",
        "appointment",
        "appointments",
        "consent",
        "follow_up",
        "message",
        "mood_entry",
        "recommendation",
        "referral",
        "risk_alert",
        "safety_event",
        "student",
        "student_data",
        "teacher_support_request",
        "therapy_note",
        "therapy_session",
        "wellness_assessment",
        "wellness_goal",
        "wellness_indicator",
        "wellness_trend",
    }
)


@dataclasses.dataclass(frozen=True)
class ShownEvent:
    """One audit row as an administrator may see it."""

    seq: int
    occurred_at: dt.datetime
    actor_id: uuid.UUID | None
    actor_role: str | None
    action: str
    outcome: str
    resource_type: str | None
    resource_id: uuid.UUID | None
    subject_student_id: uuid.UUID | None
    reason: str | None
    details: dict[str, Any]


def shown(r: m.AuditLog) -> ShownEvent:
    care = r.resource_type in CARE_RECORDS
    return ShownEvent(
        seq=r.seq,
        occurred_at=r.occurred_at,
        actor_id=r.actor_id,
        actor_role=r.actor_role.value if isinstance(r.actor_role, UserRole) else None,
        action=r.action,
        outcome=r.outcome.value,
        resource_type=r.resource_type,
        resource_id=None if care else r.resource_id,
        subject_student_id=None if care else r.subject_student_id,
        reason=r.reason,
        details={} if care else r.details,
    )


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
    stmt = select(m.AuditLog).where(
        m.AuditLog.institution_id == actor.institution_id,
        # A student's own actions on care records would name the student, so they are not listed.
        or_(
            m.AuditLog.resource_type.is_(None),
            m.AuditLog.resource_type.not_in(CARE_RECORDS),
            m.AuditLog.actor_role.is_(None),
            m.AuditLog.actor_role != UserRole.STUDENT,
        ),
    )
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
    for r in map(shown, rows):
        writer.writerow(
            _cell(v)
            for v in (
                r.seq,
                r.occurred_at.isoformat(),
                r.actor_id,
                r.actor_role,
                r.action,
                r.outcome,
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
