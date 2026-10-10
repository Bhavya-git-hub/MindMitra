"""Finding a therapist, booking and cancelling appointments, messages, and vetted resources."""

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.api.schemas import student as s
from app.application import booking, directory, messaging
from app.domain.auth.permissions import Permission
from app.domain.auth.policies import Principal
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import ResourceType

router = APIRouter(tags=["student"])
Db = Annotated[AsyncSession, Depends(get_db)]
Directory = Annotated[Principal, Depends(require_permission(Permission.THERAPIST_DIRECTORY_READ))]
Booker = Annotated[Principal, Depends(require_permission(Permission.APPOINTMENT_BOOK_OWN))]
Messenger = Annotated[Principal, Depends(require_permission(Permission.MESSAGE_PARTICIPATE_OWN))]
ResourceReader = Annotated[Principal, Depends(require_permission(Permission.RESOURCE_READ))]
Limit = Annotated[int, Query(ge=1, le=100)]


# ---- resources ------------------------------------------------------------------------------


@router.get("/resources")
async def list_resources(
    db: Db,
    principal: ResourceReader,
    resource_type: ResourceType | None = None,
    tag: Annotated[str | None, Query(max_length=40)] = None,
    q: Annotated[str | None, Query(max_length=80)] = None,
    limit: Limit = 50,
) -> list[s.ResourceOut]:
    rows = await directory.list_resources(
        db, principal, resource_type=resource_type, tag=tag, query=q, limit=limit
    )
    return [s.resource_out(r) for r in rows]


@router.get("/resources/{resource_id}")
async def get_resource(
    resource_id: uuid.UUID, db: Db, principal: ResourceReader
) -> s.ResourceDetailOut:
    return s.resource_detail_out(await directory.get_resource(db, principal, resource_id))


# ---- therapists -----------------------------------------------------------------------------


def _therapist_out(card: directory.TherapistCard) -> s.TherapistOut:
    t = card.therapist
    return s.TherapistOut(
        id=t.user_id,
        full_name=card.user.full_name,
        specialties=list(t.specialties),
        languages=list(t.languages),
        accepting_new_students=t.accepting_new_students,
        next_available_at=card.next_available_at,
        on_my_care_team=card.on_my_care_team,
    )


@router.get("/therapists")
async def list_therapists(
    db: Db,
    principal: Directory,
    specialty: Annotated[str | None, Query(max_length=80)] = None,
    language: Annotated[str | None, Query(max_length=40)] = None,
    accepting_only: bool = False,
    limit: Limit = 50,
) -> list[s.TherapistOut]:
    cards = await directory.list_therapists(
        db,
        principal,
        specialty=specialty,
        language=language,
        accepting_only=accepting_only,
        limit=limit,
    )
    return [_therapist_out(c) for c in cards]


@router.get("/therapists/{therapist_id}")
async def get_therapist(
    therapist_id: uuid.UUID, db: Db, principal: Directory
) -> s.TherapistDetailOut:
    card = await directory.get_therapist(db, principal, therapist_id)
    return s.TherapistDetailOut(**_therapist_out(card).model_dump(), bio=card.therapist.bio)


@router.get("/therapists/{therapist_id}/slots")
async def therapist_slots(therapist_id: uuid.UUID, db: Db, principal: Directory) -> list[s.SlotOut]:
    rows = await directory.open_slots(db, principal, therapist_id)
    return [
        s.SlotOut(id=a.id, starts_at=a.starts_at, ends_at=a.ends_at, mode=a.mode.value)
        for a in rows
    ]


# ---- appointments ---------------------------------------------------------------------------


@router.post("/me/appointments", status_code=201)
async def book_appointment(body: s.BookingIn, db: Db, principal: Booker) -> s.StudentAppointmentOut:
    view = await booking.book(db, principal, body.availability_id, body.reason)
    return s.appointment_view_out(view)


@router.patch("/me/appointments/{appointment_id}")
async def update_my_appointment(
    appointment_id: uuid.UUID, body: s.AppointmentPatchIn, db: Db, principal: Booker
) -> s.StudentAppointmentOut:
    assert body.status == "cancelled"  # the only student-side change; enforced by the schema
    return s.appointment_view_out(await booking.cancel(db, principal, appointment_id))


# ---- messages -------------------------------------------------------------------------------


def _message_out(r: m.Message, actor: Principal) -> s.MessageOut:
    return s.MessageOut(
        id=r.id,
        sender_id=r.sender_id,
        mine=r.sender_id == actor.user_id,
        body=r.body,
        created_at=r.created_at,
        read_at=r.read_at,
    )


@router.get("/me/conversations")
async def list_conversations(db: Db, principal: Messenger) -> list[s.ConversationOut]:
    rows = await messaging.list_conversations(db, principal)
    return [s.ConversationOut(**vars(c)) for c in rows]


@router.get("/me/conversations/{other_id}/messages")
async def conversation_messages(
    other_id: uuid.UUID,
    db: Db,
    principal: Messenger,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    before: dt.datetime | None = None,
) -> list[s.MessageOut]:
    rows = await messaging.get_messages(db, principal, other_id, limit=limit, before=before)
    return [_message_out(r, principal) for r in rows]


@router.post("/me/conversations/{other_id}/messages", status_code=201)
async def send_message(
    other_id: uuid.UUID, body: s.MessageIn, db: Db, principal: Messenger
) -> s.SentMessageOut:
    sent = await messaging.send_message(db, principal, other_id, body.body, body.client_msg_id)
    return s.SentMessageOut(
        message=_message_out(sent.message, principal),
        support=s.SUPPORT_INFO if sent.support_suggested else None,
    )


class ReadOut(BaseModel):
    marked_read: int


@router.post("/me/conversations/{other_id}/read")
async def mark_conversation_read(other_id: uuid.UUID, db: Db, principal: Messenger) -> ReadOut:
    return ReadOut(marked_read=await messaging.mark_read(db, principal, other_id))
