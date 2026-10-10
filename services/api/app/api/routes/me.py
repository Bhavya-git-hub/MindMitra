"""The signed-in user's own profile and (for students) their own records."""

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.api.schemas.student import StudentAppointmentOut, appointment_view_out
from app.api.zone import Zone, since_days
from app.application import booking, care, student_wellness
from app.domain.auth.permissions import Permission, permissions_for
from app.domain.auth.policies import Principal
from app.infrastructure.db import models as m

router = APIRouter(prefix="/me", tags=["me"])
Db = Annotated[AsyncSession, Depends(get_db)]
Limit = Annotated[int, Query(ge=1, le=200)]


class MeOut(BaseModel):
    id: uuid.UUID
    institution_id: uuid.UUID
    email: str
    full_name: str
    role: str
    status: str
    permissions: list[str]


class MoodEntryOut(BaseModel):
    id: uuid.UUID
    mood_score: int
    energy_level: int | None
    emotions: list[str]
    note: str | None = None
    logged_at: dt.datetime


class AppointmentOut(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    therapist_id: uuid.UUID
    starts_at: dt.datetime
    ends_at: dt.datetime
    mode: str
    status: str


class AIConversationOut(BaseModel):
    id: uuid.UUID
    status: str
    started_at: dt.datetime
    ended_at: dt.datetime | None


def appointment_out(a: m.Appointment) -> AppointmentOut:
    return AppointmentOut(
        id=a.id,
        student_id=a.student_id,
        therapist_id=a.therapist_id,
        starts_at=a.starts_at,
        ends_at=a.ends_at,
        mode=a.mode.value,
        status=a.status.value,
    )


@router.get("")
async def me(
    db: Db,
    principal: Annotated[Principal, Depends(require_permission(Permission.PROFILE_READ_OWN))],
) -> MeOut:
    user = await db.get(m.User, principal.user_id)
    assert user is not None  # get_principal already checked the account exists and is active
    return MeOut(
        id=user.id,
        institution_id=user.institution_id,
        email=user.email,
        full_name=user.full_name,
        role=user.role.value,
        status=user.status.value,
        permissions=sorted(p.value for p in permissions_for(principal.role)),
    )


@router.get("/wellness/mood-entries")
async def my_mood_entries(
    db: Db,
    principal: Annotated[Principal, Depends(require_permission(Permission.WELLNESS_READ_OWN))],
    zone: Zone,
    limit: Limit = 50,
    days: Annotated[int | None, Query(ge=1, le=365)] = None,
) -> list[MoodEntryOut]:
    rows = await student_wellness.list_mood_entries(
        db, principal, limit=limit, since=since_days(days, zone)
    )
    return [
        MoodEntryOut(
            id=r.id,
            mood_score=r.mood_score,
            energy_level=r.energy_level,
            emotions=list(r.emotions),
            note=r.note,
            logged_at=r.logged_at,
        )
        for r in rows
    ]


@router.get("/appointments")
async def my_appointments(
    db: Db,
    principal: Annotated[Principal, Depends(require_permission(Permission.APPOINTMENT_READ_OWN))],
    upcoming: bool | None = None,
    limit: Limit = 50,
) -> list[StudentAppointmentOut]:
    """Own appointments, newest first (or soonest first with ``upcoming=true``)."""
    rows = await booking.list_own(db, principal, upcoming=upcoming, limit=limit)
    return [appointment_view_out(v) for v in rows]


@router.get("/ai-conversations")
async def my_ai_conversations(
    db: Db,
    principal: Annotated[
        Principal, Depends(require_permission(Permission.AI_CONVERSATION_READ_OWN))
    ],
    limit: Limit = 50,
) -> list[AIConversationOut]:
    rows = await care.own_ai_conversations(db, principal, limit)
    return [
        AIConversationOut(
            id=c.id, status=c.status.value, started_at=c.started_at, ended_at=c.ended_at
        )
        for c in rows
    ]
