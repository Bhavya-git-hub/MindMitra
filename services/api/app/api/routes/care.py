"""Therapist views of students on their care team, therapy notes and appointments."""

import datetime as dt
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.api.routes.me import AppointmentOut, appointment_out
from app.application import care
from app.domain.auth.permissions import Permission
from app.domain.auth.policies import Principal
from app.infrastructure.db.enums import AppointmentStatus

router = APIRouter(tags=["care"])
Db = Annotated[AsyncSession, Depends(get_db)]
Limit = Annotated[int, Query(ge=1, le=200)]


class AssignedStudentOut(BaseModel):
    student_id: uuid.UUID
    full_name: str
    preferred_name: str | None
    year_of_study: int
    care_role: str
    since: dt.datetime


class SharedMoodEntryOut(BaseModel):
    """What a therapist sees of a consented mood entry: scores, never the private note."""

    id: uuid.UUID
    mood_score: int
    energy_level: int | None
    emotions: list[str]
    logged_at: dt.datetime


class TherapyNoteOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    version: int
    body: str
    created_at: dt.datetime
    locked_at: dt.datetime | None


class AppointmentUpdateIn(BaseModel):
    status: Literal["confirmed", "cancelled", "completed", "no_show"]


@router.get("/students")
async def my_students(
    db: Db,
    principal: Annotated[Principal, Depends(require_permission(Permission.STUDENT_READ_ASSIGNED))],
) -> list[AssignedStudentOut]:
    rows = await care.assigned_students(db, principal)
    return [
        AssignedStudentOut(
            student_id=s.user_id,
            full_name=u.full_name,
            preferred_name=s.preferred_name,
            year_of_study=s.year_of_study,
            care_role=c.role.value,
            since=c.starts_at,
        )
        for s, u, c in rows
    ]


@router.get("/students/{student_id}/mood-entries")
async def student_mood_entries(
    student_id: uuid.UUID,
    db: Db,
    principal: Annotated[Principal, Depends(require_permission(Permission.WELLNESS_READ_ASSIGNED))],
    limit: Limit = 50,
) -> list[SharedMoodEntryOut]:
    rows = await care.student_mood_entries_for_therapist(db, principal, student_id, limit)
    await db.commit()  # persists the access audit event
    return [
        SharedMoodEntryOut(
            id=r.id,
            mood_score=r.mood_score,
            energy_level=r.energy_level,
            emotions=list(r.emotions),
            logged_at=r.logged_at,
        )
        for r in rows
    ]


@router.get("/students/{student_id}/therapy-notes")
async def student_therapy_notes(
    student_id: uuid.UUID,
    db: Db,
    principal: Annotated[Principal, Depends(require_permission(Permission.THERAPY_NOTE_READ))],
) -> list[TherapyNoteOut]:
    notes = await care.therapy_notes_for_therapist(db, principal, student_id)
    out = [
        TherapyNoteOut(
            id=n.id,
            session_id=n.session_id,
            version=n.version,
            body=n.body,
            created_at=n.created_at,
            locked_at=n.locked_at,
        )
        for n in notes
    ]
    await db.commit()  # persists the access audit event (INV-7)
    return out


@router.get("/therapist/appointments")
async def therapist_appointments(
    db: Db,
    principal: Annotated[Principal, Depends(require_permission(Permission.APPOINTMENT_MANAGE))],
    status: AppointmentStatus | None = None,
    limit: Limit = 50,
) -> list[AppointmentOut]:
    rows = await care.therapist_appointments(db, principal, status, limit)
    return [appointment_out(a) for a in rows]


@router.patch("/appointments/{appointment_id}")
async def update_appointment(
    appointment_id: uuid.UUID,
    body: AppointmentUpdateIn,
    db: Db,
    principal: Annotated[Principal, Depends(require_permission(Permission.APPOINTMENT_MANAGE))],
) -> AppointmentOut:
    appt = await care.update_appointment_status(
        db, principal, appointment_id, AppointmentStatus(body.status)
    )
    out = appointment_out(appt)
    await db.commit()
    return out
