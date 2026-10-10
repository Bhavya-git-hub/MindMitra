"""Administrator endpoints for notification and safety settings and crisis contacts."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.api.schemas import admin as s
from app.application import institution_settings as cfg
from app.domain.auth.permissions import Permission
from app.domain.auth.policies import Principal
from app.infrastructure.db.enums import CrisisContactKind

router = APIRouter(prefix="/admin/settings", tags=["admin"])
Db = Annotated[AsyncSession, Depends(get_db)]
Notifications = Annotated[
    Principal, Depends(require_permission(Permission.NOTIFICATION_CONFIG_MANAGE))
]
Safety = Annotated[Principal, Depends(require_permission(Permission.SAFETY_CONFIG_MANAGE))]


@router.get("/notifications")
async def get_notifications(db: Db, principal: Notifications) -> s.NotificationSettingsOut:
    return s.settings_out(await cfg.load(db, principal.institution_id)).notifications


@router.patch("/notifications")
async def update_notifications(
    body: s.NotificationSettingsPatchIn, db: Db, principal: Notifications
) -> s.NotificationSettingsOut:
    await cfg.update_notifications(db, principal, body.model_dump(exclude_unset=True))
    return s.settings_out(await cfg.load(db, principal.institution_id)).notifications


@router.get("/safety")
async def get_safety(db: Db, principal: Safety) -> s.SafetySettingsOut:
    return s.settings_out(await cfg.load(db, principal.institution_id)).safety


@router.patch("/safety")
async def update_safety(
    body: s.SafetySettingsPatchIn, db: Db, principal: Safety
) -> s.SafetySettingsOut:
    await cfg.update_safety(db, principal, body.model_dump(exclude_unset=True))
    return s.settings_out(await cfg.load(db, principal.institution_id)).safety


@router.get("/crisis-contacts")
async def list_contacts(db: Db, principal: Safety) -> list[s.CrisisContactOut]:
    return [s.contact_out(c) for c in await cfg.list_contacts(db, principal)]


@router.post("/crisis-contacts", status_code=status.HTTP_201_CREATED)
async def create_contact(body: s.CrisisContactIn, db: Db, principal: Safety) -> s.CrisisContactOut:
    data = body.model_dump()
    data["kind"] = CrisisContactKind(data["kind"])
    return s.contact_out(await cfg.create_contact(db, principal, data))


@router.patch("/crisis-contacts/{contact_id}")
async def update_contact(
    contact_id: uuid.UUID, body: s.CrisisContactPatchIn, db: Db, principal: Safety
) -> s.CrisisContactOut:
    patch = body.model_dump(exclude_unset=True)
    return s.contact_out(await cfg.update_contact(db, principal, contact_id, patch))


@router.delete("/crisis-contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(contact_id: uuid.UUID, db: Db, principal: Safety) -> Response:
    await cfg.delete_contact(db, principal, contact_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
