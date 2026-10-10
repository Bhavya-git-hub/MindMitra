"""The AI wellness companion for students (ADR 0010).

Only the owning student can see or use a conversation; teachers, therapists and
administrators hold neither companion permission. A crisis message is answered with crisis
contacts and alerts a person even when the companion is switched off or the student is over
their limit.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import app_state, get_db, require_permission
from app.api.schemas import companion as s
from app.application import companion as uc
from app.domain.auth.permissions import Permission
from app.domain.auth.policies import Principal

router = APIRouter(prefix="/companion", tags=["companion"])
Db = Annotated[AsyncSession, Depends(get_db)]
Reader = Annotated[Principal, Depends(require_permission(Permission.AI_CONVERSATION_READ_OWN))]
User = Annotated[Principal, Depends(require_permission(Permission.AI_COMPANION_USE_OWN))]


@router.get("/status")
async def companion_status(request: Request, db: Db, principal: User) -> s.CompanionStatusOut:
    state = app_state(request)
    a = await uc.availability(db, principal, state.settings, configured=state.companion is not None)
    return s.CompanionStatusOut(
        available=a.available,
        reason=a.reason,
        daily_limit=a.daily_limit,
        remaining_today=a.remaining_today,
        keeps_history=a.keeps_history,
        retention_hours=a.retention_hours,
        disclaimer=uc.DISCLAIMER,
    )


@router.get("/conversations")
async def list_conversations(
    db: Db, principal: Reader, limit: Annotated[int, Query(ge=1, le=100)] = 50
) -> list[s.ConversationOut]:
    return [s.conversation_out(c) for c in await uc.list_conversations(db, principal, limit)]


@router.post("/conversations", status_code=status.HTTP_201_CREATED)
async def start_conversation(request: Request, db: Db, principal: User) -> s.ConversationOut:
    state = app_state(request)
    conv = await uc.start_conversation(
        db, principal, state.settings, configured=state.companion is not None
    )
    return s.conversation_out(conv)


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID, db: Db, principal: Reader
) -> s.ConversationDetailOut:
    conv, messages = await uc.get_conversation(db, principal, conversation_id)
    return s.ConversationDetailOut(
        conversation=s.conversation_out(conv), messages=[s.message_out(x) for x in messages]
    )


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: uuid.UUID,
    body: s.CompanionMessageIn,
    request: Request,
    db: Db,
    principal: User,
) -> s.ExchangeOut:
    state = app_state(request)
    ex = await uc.send_message(
        db,
        principal,
        conversation_id,
        body.content,
        settings=state.settings,
        client=state.companion,
        limiter=state.companion_limiter,
    )
    return s.ExchangeOut(
        conversation=s.conversation_out(ex.conversation),
        message=s.message_out(ex.message),
        reply=s.message_out(ex.reply),
        support=s.support_out(ex.support) if ex.support else None,
        disclaimer=uc.DISCLAIMER,
    )


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: uuid.UUID, db: Db, principal: User) -> Response:
    await uc.delete_conversation(db, principal, conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
