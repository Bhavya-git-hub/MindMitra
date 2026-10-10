"""A therapist's own follow-up reminders about students on their care team."""

import dataclasses
import datetime as dt
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.access import NotFound, enforce
from app.application.errors import InvalidInput
from app.application.therapist_access import active_students, require_verified, student_in_care
from app.application.timeutil import local_today, now_utc
from app.domain.auth.policies import Principal, can_manage_own_therapist_record
from app.infrastructure.db import models as m
from app.infrastructure.db.audit import append_audit_event
from app.infrastructure.db.enums import AuditOutcome, FollowUpKind, FollowUpStatus, UserRole
from app.infrastructure.db.ids import uuid7

MAX_NOTE = 1000
MAX_AHEAD = dt.timedelta(days=365)


@dataclasses.dataclass
class FollowUpView:
    follow_up: m.FollowUp
    student_name: str
    overdue: bool


async def _audit(
    db: AsyncSession, actor: Principal, action: str, row: m.FollowUp, **d: object
) -> None:
    await append_audit_event(
        db,
        institution_id=actor.institution_id,
        actor_id=actor.user_id,
        actor_role=UserRole.THERAPIST,
        action=action,
        outcome=AuditOutcome.ALLOWED,
        resource_type="follow_up",
        resource_id=row.id,
        subject_student_id=row.student_id,
        details=dict(d),
    )


def _clean_note(note: str | None) -> str | None:
    text = (note or "").strip()
    if len(text) > MAX_NOTE:
        raise InvalidInput(f"A follow-up note can be up to {MAX_NOTE} characters.")
    return text or None


def _check_due(due_on: dt.date, zone: ZoneInfo) -> None:
    today = local_today(zone)
    if due_on < today:
        raise InvalidInput("The due date can't be in the past.")
    if due_on > today + MAX_AHEAD:
        raise InvalidInput("Please choose a date within the next year.")


async def _name(db: AsyncSession, student_id: uuid.UUID) -> str:
    return await db.scalar(select(m.User.full_name).where(m.User.id == student_id)) or ""


async def list_follow_ups(
    db: AsyncSession,
    actor: Principal,
    *,
    status: FollowUpStatus | None,
    student_id: uuid.UUID | None,
    zone: ZoneInfo,
    limit: int,
) -> list[FollowUpView]:
    await require_verified(db, actor, "follow_up.list")
    stmt = (
        select(m.FollowUp, m.User.full_name)
        .join(m.User, m.User.id == m.FollowUp.student_id)
        .where(
            m.FollowUp.therapist_id == actor.user_id,
            m.FollowUp.institution_id == actor.institution_id,
            # Reminders about students who have left my care team are no longer mine to see.
            m.FollowUp.student_id.in_(active_students(actor)),
        )
    )
    if status is not None:
        stmt = stmt.where(m.FollowUp.status == status)
    if student_id is not None:
        stmt = stmt.where(m.FollowUp.student_id == student_id)
    rows = (
        await db.execute(
            stmt.order_by(m.FollowUp.due_on, m.FollowUp.created_at).limit(min(limit, 200))
        )
    ).all()
    today = local_today(zone)
    return [
        FollowUpView(f, name, f.status is FollowUpStatus.OPEN and f.due_on < today)
        for f, name in rows
    ]


async def create_follow_up(
    db: AsyncSession,
    actor: Principal,
    *,
    student_id: uuid.UUID,
    kind: FollowUpKind,
    due_on: dt.date,
    note: str | None,
    session_id: uuid.UUID | None,
    zone: ZoneInfo,
) -> FollowUpView:
    await student_in_care(
        db, actor, student_id, action="follow_up.create", resource_type="follow_up"
    )
    _check_due(due_on, zone)
    clean = _clean_note(note)
    if session_id is not None:
        session = await db.get(m.TherapySession, session_id)
        if (
            session is None
            or session.therapist_id != actor.user_id
            or session.student_id != student_id
        ):
            raise NotFound
    row = m.FollowUp(
        id=uuid7(),
        institution_id=actor.institution_id,
        therapist_id=actor.user_id,
        student_id=student_id,
        session_id=session_id,
        kind=kind,
        status=FollowUpStatus.OPEN,
        due_on=due_on,
        note=clean,
    )
    db.add(row)
    await db.flush()
    await _audit(db, actor, "follow_up.create", row, kind=kind.value)
    await db.commit()
    return FollowUpView(row, await _name(db, student_id), False)


async def update_follow_up(
    db: AsyncSession,
    actor: Principal,
    follow_up_id: uuid.UUID,
    *,
    status: FollowUpStatus | None,
    due_on: dt.date | None,
    note: str | None,
    zone: ZoneInfo,
) -> FollowUpView:
    await require_verified(db, actor, "follow_up.update")
    row = await db.get(m.FollowUp, follow_up_id, with_for_update=True)
    if row is None:
        raise NotFound
    enforce(
        can_manage_own_therapist_record(
            actor, institution_id=row.institution_id, therapist_id=row.therapist_id
        ),
        action="follow_up.update",
        resource_type="follow_up",
        resource_id=row.id,
        subject_student_id=row.student_id,
    )
    changed: list[str] = []
    if due_on is not None and due_on != row.due_on:
        _check_due(due_on, zone)
        row.due_on = due_on
        changed.append("due_on")
    if note is not None:
        row.note = _clean_note(note)
        changed.append("note")
    if status is not None and status is not row.status:
        row.status = status
        row.completed_at = now_utc() if status is FollowUpStatus.DONE else None
        changed.append("status")
    await _audit(db, actor, "follow_up.update", row, fields=changed, status=row.status.value)
    await db.commit()
    return FollowUpView(
        row,
        await _name(db, row.student_id),
        row.status is FollowUpStatus.OPEN and row.due_on < local_today(zone),
    )
