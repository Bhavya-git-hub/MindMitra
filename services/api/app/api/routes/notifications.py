"""Everyone's in-app notifications: list, count unread, mark read. Own notifications only."""

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.application import notifications
from app.domain.auth.permissions import Permission
from app.domain.auth.policies import Principal
from app.infrastructure.db import models as m

router = APIRouter(prefix="/me/notifications", tags=["notifications"])
Db = Annotated[AsyncSession, Depends(get_db)]
# Every role reads its own profile; notifications are part of it.
Owner = Annotated[Principal, Depends(require_permission(Permission.PROFILE_READ_OWN))]


class NotificationOut(BaseModel):
    id: uuid.UUID
    type: str
    priority: str
    title: str
    payload: dict[str, str]
    created_at: dt.datetime
    read_at: dt.datetime | None


class InboxOut(BaseModel):
    items: list[NotificationOut]
    unread: int


class UnreadOut(BaseModel):
    unread: int


class MarkedOut(BaseModel):
    marked_read: int


def _out(n: m.Notification) -> NotificationOut:
    return NotificationOut(
        id=n.id,
        type=n.type.value,
        priority=n.priority.value,
        title=n.title,
        payload={k: str(v) for k, v in n.payload.items()},
        created_at=n.created_at,
        read_at=n.read_at,
    )


@router.get("")
async def list_notifications(
    db: Db,
    principal: Owner,
    unread: bool = False,
    before: dt.datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> InboxOut:
    box = await notifications.inbox(db, principal, unread_only=unread, before=before, limit=limit)
    return InboxOut(items=[_out(n) for n in box.items], unread=box.unread)


@router.get("/unread-count")
async def unread_count(db: Db, principal: Owner) -> UnreadOut:
    return UnreadOut(unread=await notifications.unread_count(db, principal))


@router.post("/{notification_id}/read", status_code=204)
async def mark_read(notification_id: uuid.UUID, db: Db, principal: Owner) -> None:
    await notifications.mark_read(db, principal, notification_id)


@router.post("/read-all")
async def mark_all_read(db: Db, principal: Owner) -> MarkedOut:
    return MarkedOut(marked_read=await notifications.mark_all_read(db, principal))
