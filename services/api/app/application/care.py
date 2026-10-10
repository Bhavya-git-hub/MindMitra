"""Read/update use cases for students' own records and their therapists' views.

Every function receives the authenticated ``Principal``, loads the facts a policy needs, asks
the policy, and only then reads data. Reads of Sensitive or Clinical-Confidential data by
someone other than the owner are written to the audit log (INV-7).
"""

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.access import NotFound, enforce, has_active_care_link, has_active_consent
from app.application.therapist_access import require_verified
from app.domain.auth.policies import (
    Principal,
    can_manage_appointment,
    can_read_ai_conversation,
    can_read_student_wellness,
    can_read_therapy_note,
)
from app.infrastructure.db import models as m
from app.infrastructure.db.audit import append_audit_event
from app.infrastructure.db.enums import (
    AppointmentStatus,
    AuditOutcome,
    CareRole,
    ConsentScope,
    NotificationType,
    UserRole,
)
from app.infrastructure.db.ids import uuid7

MAX_LIMIT = 200


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


async def _audit_read(
    db: AsyncSession,
    actor: Principal,
    action: str,
    resource_type: str,
    *,
    student_id: uuid.UUID,
    count: int,
) -> None:
    await append_audit_event(
        db,
        institution_id=actor.institution_id,
        actor_id=actor.user_id,
        actor_role=UserRole(actor.role.value),
        action=action,
        outcome=AuditOutcome.ALLOWED,
        resource_type=resource_type,
        subject_student_id=student_id,
        details={"count": count},
    )


# ---- student: own records -------------------------------------------------------------------


async def own_mood_entries(db: AsyncSession, actor: Principal, limit: int) -> list[m.MoodEntry]:
    enforce(
        can_read_student_wellness(
            actor,
            student_id=actor.user_id,
            student_institution_id=actor.institution_id,
            has_active_care_link=False,
            has_sharing_consent=False,
        ),
        action="mood_entry.list",
        resource_type="mood_entry",
        subject_student_id=actor.user_id,
    )
    rows = await db.scalars(
        select(m.MoodEntry)
        .where(
            m.MoodEntry.student_id == actor.user_id,
            m.MoodEntry.institution_id == actor.institution_id,
        )
        .order_by(m.MoodEntry.logged_at.desc())
        .limit(min(limit, MAX_LIMIT))
    )
    return list(rows)


async def own_appointments(db: AsyncSession, actor: Principal, limit: int) -> list[m.Appointment]:
    rows = await db.scalars(
        select(m.Appointment)
        .where(
            m.Appointment.student_id == actor.user_id,
            m.Appointment.institution_id == actor.institution_id,
        )
        .order_by(m.Appointment.starts_at.desc())
        .limit(min(limit, MAX_LIMIT))
    )
    return list(rows)


async def own_ai_conversations(
    db: AsyncSession, actor: Principal, limit: int
) -> list[m.AIConversation]:
    rows = list(
        await db.scalars(
            select(m.AIConversation)
            .where(
                m.AIConversation.student_id == actor.user_id,
                m.AIConversation.deleted_at.is_(None),
            )
            .order_by(m.AIConversation.started_at.desc())
            .limit(min(limit, MAX_LIMIT))
        )
    )
    for conv in rows:  # defence in depth: the query is already scoped to the caller
        enforce(
            can_read_ai_conversation(
                actor, owner_student_id=conv.student_id, institution_id=conv.institution_id
            ),
            action="ai_conversation.list",
            resource_type="ai_conversation",
            resource_id=conv.id,
        )
    return rows


# ---- therapist: assigned students ------------------------------------------------------------


async def assigned_students(
    db: AsyncSession, actor: Principal
) -> list[tuple[m.Student, m.User, m.CareTeamMember]]:
    await require_verified(db, actor, "student.list")
    now = _now()
    rows = await db.execute(
        select(m.Student, m.User, m.CareTeamMember)
        .join(m.User, m.User.id == m.Student.user_id)
        .join(m.CareTeamMember, m.CareTeamMember.student_id == m.Student.user_id)
        .where(
            m.CareTeamMember.therapist_id == actor.user_id,
            m.CareTeamMember.institution_id == actor.institution_id,
            m.CareTeamMember.starts_at <= now,
            (m.CareTeamMember.ends_at.is_(None)) | (m.CareTeamMember.ends_at > now),
        )
        .order_by(m.User.full_name)
    )
    return [(s, u, c) for s, u, c in rows.all()]


async def _student_or_hidden(
    db: AsyncSession, actor: Principal, student_id: uuid.UUID
) -> m.Student:
    student = await db.get(m.Student, student_id)
    # Another institution's student is indistinguishable from a missing one.
    if student is None or student.institution_id != actor.institution_id:
        raise NotFound
    return student


async def student_mood_entries_for_therapist(
    db: AsyncSession, actor: Principal, student_id: uuid.UUID, limit: int
) -> list[m.MoodEntry]:
    await require_verified(db, actor, "mood_entry.list")
    student = await _student_or_hidden(db, actor, student_id)
    linked = await has_active_care_link(
        db, therapist_id=actor.user_id, student_id=student_id, now=_now()
    )
    consent = linked and await has_active_consent(
        db, user_id=student_id, scope=ConsentScope.SHARE_MOOD_WITH_CARE_TEAM
    )
    enforce(
        can_read_student_wellness(
            actor,
            student_id=student_id,
            student_institution_id=student.institution_id,
            has_active_care_link=linked,
            has_sharing_consent=consent,
        ),
        action="mood_entry.list",
        resource_type="mood_entry",
        subject_student_id=student_id,
    )
    rows = list(
        await db.scalars(
            select(m.MoodEntry)
            .where(m.MoodEntry.student_id == student_id)
            .order_by(m.MoodEntry.logged_at.desc())
            .limit(min(limit, MAX_LIMIT))
        )
    )
    await _audit_read(
        db, actor, "mood_entry.list", "mood_entry", student_id=student_id, count=len(rows)
    )
    return rows


async def therapy_notes_for_therapist(
    db: AsyncSession, actor: Principal, student_id: uuid.UUID
) -> list[m.TherapyNote]:
    """Notes the caller wrote about this student. Other therapists' notes are never returned."""
    await require_verified(db, actor, "therapy_note.list")
    student = await _student_or_hidden(db, actor, student_id)
    linked = await has_active_care_link(
        db, therapist_id=actor.user_id, student_id=student_id, now=_now()
    )
    enforce(
        can_read_therapy_note(
            actor,
            note_institution_id=student.institution_id,
            note_author_id=actor.user_id,
            has_active_care_link=linked,
        ),
        action="therapy_note.list",
        resource_type="therapy_note",
        subject_student_id=student_id,
    )
    notes = list(
        await db.scalars(
            select(m.TherapyNote)
            .join(m.TherapySession, m.TherapySession.id == m.TherapyNote.session_id)
            .where(
                m.TherapySession.student_id == student_id,
                m.TherapyNote.author_id == actor.user_id,
                m.TherapyNote.institution_id == actor.institution_id,
            )
            .order_by(m.TherapyNote.created_at.desc())
        )
    )
    for note in notes:
        enforce(
            can_read_therapy_note(
                actor,
                note_institution_id=note.institution_id,
                note_author_id=note.author_id,
                has_active_care_link=linked,
            ),
            action="therapy_note.read",
            resource_type="therapy_note",
            resource_id=note.id,
            subject_student_id=student_id,
        )
    await _audit_read(
        db, actor, "therapy_note.list", "therapy_note", student_id=student_id, count=len(notes)
    )
    return notes


# ---- therapist: appointments -----------------------------------------------------------------


async def therapist_appointments(
    db: AsyncSession, actor: Principal, status: AppointmentStatus | None, limit: int
) -> list[m.Appointment]:
    await require_verified(db, actor, "appointment.list")
    stmt = select(m.Appointment).where(
        m.Appointment.therapist_id == actor.user_id,
        m.Appointment.institution_id == actor.institution_id,
    )
    if status is not None:
        stmt = stmt.where(m.Appointment.status == status)
    rows = await db.scalars(
        stmt.order_by(m.Appointment.starts_at.desc()).limit(min(limit, MAX_LIMIT))
    )
    return list(rows)


ALLOWED_TRANSITIONS: dict[AppointmentStatus, frozenset[AppointmentStatus]] = {
    AppointmentStatus.REQUESTED: frozenset(
        {AppointmentStatus.CONFIRMED, AppointmentStatus.CANCELLED}
    ),
    AppointmentStatus.CONFIRMED: frozenset(
        {AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED, AppointmentStatus.NO_SHOW}
    ),
}


class InvalidTransition(Exception):
    pass


async def _ensure_care_link(db: AsyncSession, appt: m.Appointment) -> None:
    """Confirming a first appointment puts the student on the therapist's care team.

    That is what lets the two of them message each other; it does not by itself let the
    therapist see any wellbeing data (that also needs the student's consent).
    """
    now = _now()
    if await has_active_care_link(
        db, therapist_id=appt.therapist_id, student_id=appt.student_id, now=now
    ):
        return
    has_primary = await db.scalar(
        select(m.CareTeamMember.id).where(
            m.CareTeamMember.student_id == appt.student_id,
            m.CareTeamMember.role == CareRole.PRIMARY,
            m.CareTeamMember.ends_at.is_(None),
        )
    )
    db.add(
        m.CareTeamMember(
            institution_id=appt.institution_id,
            student_id=appt.student_id,
            therapist_id=appt.therapist_id,
            role=CareRole.SECONDARY if has_primary else CareRole.PRIMARY,
            starts_at=now,
        )
    )
    await db.flush()


async def update_appointment_status(
    db: AsyncSession, actor: Principal, appointment_id: uuid.UUID, new_status: AppointmentStatus
) -> m.Appointment:
    await require_verified(db, actor, "appointment.update")
    appt = await db.get(m.Appointment, appointment_id, with_for_update=True)
    if appt is None:
        raise NotFound
    enforce(
        can_manage_appointment(
            actor, appointment_institution_id=appt.institution_id, therapist_id=appt.therapist_id
        ),
        action="appointment.update",
        resource_type="appointment",
        resource_id=appt.id,
        subject_student_id=appt.student_id,
    )
    if new_status not in ALLOWED_TRANSITIONS.get(appt.status, frozenset()):
        raise InvalidTransition(f"cannot change an appointment from {appt.status} to {new_status}")
    old = appt.status
    appt.status = new_status
    if new_status is AppointmentStatus.CONFIRMED:
        await _ensure_care_link(db, appt)
    if new_status is AppointmentStatus.CANCELLED:
        appt.cancelled_at = _now()
        appt.cancelled_by = actor.user_id
    if new_status in (AppointmentStatus.CONFIRMED, AppointmentStatus.CANCELLED):
        # Identifiers only: no names, times or reasons (notify schema rules).
        db.add(
            m.Notification(
                id=uuid7(),
                institution_id=appt.institution_id,
                user_id=appt.student_id,
                type=NotificationType.APPOINTMENT_UPDATE,
                title="Your appointment was "
                + ("confirmed" if new_status is AppointmentStatus.CONFIRMED else "cancelled"),
                payload={"appointment_id": str(appt.id), "event": new_status.value},
            )
        )
    await append_audit_event(
        db,
        institution_id=actor.institution_id,
        actor_id=actor.user_id,
        actor_role=UserRole.THERAPIST,
        action="appointment.update",
        outcome=AuditOutcome.ALLOWED,
        resource_type="appointment",
        resource_id=appt.id,
        subject_student_id=appt.student_id,
        details={"from": old.value, "to": new_status.value},
    )
    return appt
