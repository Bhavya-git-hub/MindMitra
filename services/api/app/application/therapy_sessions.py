"""Delivered sessions and the confidential notes written about them.

Session notes are Clinical-Confidential: only the therapist who delivered the session can read
or write them, only while the student is on their care team, and every read and write is
audited without any note content. Teachers, administrators, students and other therapists have
no path to a note at all (the policies deny them and the queries are scoped to the author).
"""

import dataclasses
import datetime as dt
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.access import NotFound, enforce, has_active_care_link
from app.application.errors import InvalidInput
from app.application.therapist_access import active_students, require_verified
from app.application.timeutil import now_utc
from app.domain.auth.policies import (
    Principal,
    can_manage_own_therapist_record,
    can_read_therapy_note,
    can_write_therapy_note,
)
from app.infrastructure.db import models as m
from app.infrastructure.db.audit import append_audit_event
from app.infrastructure.db.enums import (
    AppointmentStatus,
    AuditOutcome,
    TherapySessionStatus,
    UserRole,
)
from app.infrastructure.db.ids import uuid7

EARLY_START = dt.timedelta(minutes=15)
LATE_START = dt.timedelta(hours=24)
MAX_NOTE_LENGTH = 20_000


def can_start(appt: m.Appointment, has_session: bool, now: dt.datetime | None = None) -> bool:
    """A confirmed appointment with no session yet, from 15 minutes before it begins until a
    day after it ends."""
    at = now or now_utc()
    return (
        appt.status is AppointmentStatus.CONFIRMED
        and not has_session
        and appt.starts_at - EARLY_START <= at <= appt.ends_at + LATE_START
    )


@dataclasses.dataclass
class SessionView:
    session: m.TherapySession
    appointment: m.Appointment
    student_name: str
    note_versions: int


@dataclasses.dataclass
class NoteView:
    note: m.TherapyNote
    versions: list[tuple[int, dt.datetime]]  # (version, written at), oldest first


async def _audit(
    db: AsyncSession,
    actor: Principal,
    action: str,
    session: m.TherapySession,
    resource_type: str,
    **details: object,
) -> None:
    await append_audit_event(
        db,
        institution_id=actor.institution_id,
        actor_id=actor.user_id,
        actor_role=UserRole.THERAPIST,
        action=action,
        outcome=AuditOutcome.ALLOWED,
        resource_type=resource_type,
        resource_id=session.id,
        subject_student_id=session.student_id,
        details=dict(details),
    )


async def _own_session(
    db: AsyncSession, actor: Principal, session_id: uuid.UUID, action: str, *, lock: bool = False
) -> m.TherapySession:
    session = await db.get(m.TherapySession, session_id, with_for_update=lock)
    if session is None:
        raise NotFound
    enforce(
        can_manage_own_therapist_record(
            actor, institution_id=session.institution_id, therapist_id=session.therapist_id
        ),
        action=action,
        resource_type="therapy_session",
        resource_id=session.id,
        subject_student_id=session.student_id,
    )
    return session


async def _versions(db: AsyncSession, session_id: uuid.UUID) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(m.TherapyNote)
            .where(m.TherapyNote.session_id == session_id)
        )
        or 0
    )


async def _view(db: AsyncSession, session: m.TherapySession) -> SessionView:
    appt = await db.get(m.Appointment, session.appointment_id)
    name = await db.scalar(select(m.User.full_name).where(m.User.id == session.student_id))
    assert appt is not None
    return SessionView(session, appt, name or "", await _versions(db, session.id))


async def list_sessions(
    db: AsyncSession, actor: Principal, status: TherapySessionStatus | None, limit: int
) -> list[SessionView]:
    await require_verified(db, actor, "therapy_session.list")
    stmt = select(m.TherapySession).where(
        m.TherapySession.therapist_id == actor.user_id,
        m.TherapySession.institution_id == actor.institution_id,
        m.TherapySession.student_id.in_(active_students(actor)),
    )
    if status is not None:
        stmt = stmt.where(m.TherapySession.status == status)
    rows = await db.scalars(
        stmt.order_by(m.TherapySession.started_at.desc()).limit(min(limit, 200))
    )
    return [await _view(db, s) for s in rows]


async def start_session(
    db: AsyncSession, actor: Principal, appointment_id: uuid.UUID
) -> SessionView:
    await require_verified(db, actor, "therapy_session.start")
    appt = await db.get(m.Appointment, appointment_id, with_for_update=True)
    if appt is None:
        raise NotFound
    enforce(
        can_manage_own_therapist_record(
            actor, institution_id=appt.institution_id, therapist_id=appt.therapist_id
        ),
        action="therapy_session.start",
        resource_type="appointment",
        resource_id=appt.id,
        subject_student_id=appt.student_id,
    )
    if appt.status is not AppointmentStatus.CONFIRMED:
        raise InvalidInput("Only a confirmed appointment can be started.")
    now = now_utc()
    if now < appt.starts_at - EARLY_START:
        raise InvalidInput("This appointment can be started 15 minutes before it begins.")
    if now > appt.ends_at + LATE_START:
        raise InvalidInput("This appointment ended more than a day ago. Mark it as a no-show.")
    existing = await db.scalar(
        select(m.TherapySession).where(m.TherapySession.appointment_id == appt.id)
    )
    if existing is not None:
        return await _view(db, existing)  # starting twice is harmless
    session = m.TherapySession(
        id=uuid7(),
        institution_id=appt.institution_id,
        appointment_id=appt.id,
        student_id=appt.student_id,
        therapist_id=appt.therapist_id,
        status=TherapySessionStatus.IN_PROGRESS,
        started_at=now,
    )
    db.add(session)
    await db.flush()
    await _audit(db, actor, "therapy_session.start", session, "therapy_session")
    await db.commit()
    return await _view(db, session)


async def finish_session(
    db: AsyncSession, actor: Principal, session_id: uuid.UUID, outcome: TherapySessionStatus
) -> SessionView:
    await require_verified(db, actor, "therapy_session.update")
    session = await _own_session(db, actor, session_id, "therapy_session.update", lock=True)
    if outcome not in (TherapySessionStatus.COMPLETED, TherapySessionStatus.ABANDONED):
        raise InvalidInput("A session can be completed or abandoned.")
    if session.status is not TherapySessionStatus.IN_PROGRESS:
        raise InvalidInput("This session has already been closed.")
    now = now_utc()
    if outcome is TherapySessionStatus.COMPLETED:
        session.status = TherapySessionStatus.COMPLETED
        session.ended_at = now
        session.duration_minutes = min(
            max(int((now - session.started_at).total_seconds() // 60), 0), 600
        )
        appt = await db.get(m.Appointment, session.appointment_id, with_for_update=True)
        if appt is not None and appt.status is AppointmentStatus.CONFIRMED:
            appt.status = AppointmentStatus.COMPLETED
    else:
        session.status = TherapySessionStatus.ABANDONED
    await _audit(db, actor, "therapy_session.update", session, "therapy_session", to=outcome.value)
    await db.commit()
    return await _view(db, session)


# ---- notes ---------------------------------------------------------------------------------


async def _link(db: AsyncSession, actor: Principal, session: m.TherapySession) -> bool:
    return await has_active_care_link(
        db, therapist_id=actor.user_id, student_id=session.student_id, now=now_utc()
    )


async def get_note(
    db: AsyncSession, actor: Principal, session_id: uuid.UUID, version: int | None
) -> NoteView | None:
    """The latest (or a chosen) version of this session's note; ``None`` if none written yet.
    A therapist who is not the author, or who no longer has the student on their care team,
    gets "not found"."""
    await require_verified(db, actor, "therapy_note.read")
    session = await db.get(m.TherapySession, session_id)
    if session is None or session.institution_id != actor.institution_id:
        raise NotFound
    linked = await _link(db, actor, session)
    enforce(
        can_read_therapy_note(
            actor,
            note_institution_id=session.institution_id,
            note_author_id=session.therapist_id,
            has_active_care_link=linked,
        ),
        action="therapy_note.read",
        resource_type="therapy_note",
        resource_id=session.id,
        subject_student_id=session.student_id,
    )
    stmt = select(m.TherapyNote).where(
        m.TherapyNote.session_id == session.id, m.TherapyNote.author_id == actor.user_id
    )
    stmt = (
        stmt.where(m.TherapyNote.version == version)
        if version
        else stmt.order_by(m.TherapyNote.version.desc())
    )
    note = await db.scalar(stmt.limit(1))
    if note is None:
        if version:
            raise NotFound
        return None
    versions = [
        (v, at)
        for v, at in (
            await db.execute(
                select(m.TherapyNote.version, m.TherapyNote.created_at)
                .where(m.TherapyNote.session_id == session.id)
                .order_by(m.TherapyNote.version)
            )
        ).all()
    ]
    await _audit(db, actor, "therapy_note.read", session, "therapy_note", version=note.version)
    await db.commit()  # persists the access audit event
    return NoteView(note, versions)


async def save_note(
    db: AsyncSession, actor: Principal, session_id: uuid.UUID, body: str
) -> NoteView:
    """Writes the first version, or a new version that supersedes the previous one."""
    await require_verified(db, actor, "therapy_note.write")
    session = await db.get(m.TherapySession, session_id, with_for_update=True)
    if session is None or session.institution_id != actor.institution_id:
        raise NotFound
    linked = await _link(db, actor, session)
    enforce(
        can_write_therapy_note(
            actor,
            session_institution_id=session.institution_id,
            session_therapist_id=session.therapist_id,
            has_active_care_link=linked,
        ),
        action="therapy_note.write",
        resource_type="therapy_note",
        resource_id=session.id,
        subject_student_id=session.student_id,
    )
    text = body.strip()
    if not text:
        raise InvalidInput("Please write something before saving.")
    if len(text) > MAX_NOTE_LENGTH:
        raise InvalidInput(f"A note can be up to {MAX_NOTE_LENGTH:,} characters.")
    previous = await db.scalar(
        select(m.TherapyNote)
        .where(m.TherapyNote.session_id == session.id)
        .order_by(m.TherapyNote.version.desc())
        .limit(1)
    )
    now = now_utc()
    if previous is not None:
        previous.locked_at = now  # superseded: kept for the record, never edited
    note = m.TherapyNote(
        id=uuid7(),
        institution_id=session.institution_id,
        session_id=session.id,
        author_id=actor.user_id,
        version=(previous.version + 1) if previous else 1,
        body=text,
    )
    db.add(note)
    await db.flush()
    await _audit(db, actor, "therapy_note.write", session, "therapy_note", version=note.version)
    await db.commit()
    versions = [
        (v, at)
        for v, at in (
            await db.execute(
                select(m.TherapyNote.version, m.TherapyNote.created_at)
                .where(m.TherapyNote.session_id == session.id)
                .order_by(m.TherapyNote.version)
            )
        ).all()
    ]
    return NoteView(note, versions)
