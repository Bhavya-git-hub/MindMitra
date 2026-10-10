"""Notification and safety settings, and the crisis contacts students are shown.

Settings are numbers and switches validated by ``domain.settings``; an institution that never
saved anything gets the defaults. Other use cases read them through ``load`` so a change takes
effect on the next request. Every change is audited with the field names and values (never free
text), and crisis contacts keep at least one active emergency number.
"""

import dataclasses
import uuid
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.access import NotFound, enforce
from app.application.errors import InvalidInput
from app.domain.auth.policies import Principal, can_administer, can_edit_resource
from app.domain.settings import NotificationSettings, SafetySettings, merged
from app.infrastructure.db import models as m
from app.infrastructure.db.audit import append_audit_event
from app.infrastructure.db.enums import AuditOutcome, CrisisContactKind, UserRole


@dataclasses.dataclass(frozen=True)
class Settings:
    notifications: NotificationSettings
    safety: SafetySettings


async def load(db: AsyncSession, institution_id: uuid.UUID) -> Settings:
    row = await db.scalar(
        select(m.InstitutionSettings).where(m.InstitutionSettings.institution_id == institution_id)
    )
    if row is None:
        return Settings(NotificationSettings(), SafetySettings())
    return Settings(
        merged(NotificationSettings, row.notifications), merged(SafetySettings, row.safety)
    )


async def _audit(
    db: AsyncSession, actor: Principal, action: str, resource_id: uuid.UUID | None, **details: str
) -> None:
    await append_audit_event(
        db,
        institution_id=actor.institution_id,
        actor_id=actor.user_id,
        actor_role=UserRole.ADMINISTRATOR,
        action=action,
        outcome=AuditOutcome.ALLOWED,
        resource_type="settings" if action.startswith("settings") else "crisis_contact",
        resource_id=resource_id,
        details=details,
    )


def _changes(before: BaseModel, after: BaseModel) -> str:
    old, new = before.model_dump(), after.model_dump()
    return "; ".join(f"{k}: {old[k]} -> {new[k]}" for k in new if old[k] != new[k])[:190]


async def _save(db: AsyncSession, actor: Principal, column: str, value: dict[str, Any]) -> None:
    stmt = pg_insert(m.InstitutionSettings).values(
        institution_id=actor.institution_id, updated_by=actor.user_id, **{column: value}
    )
    await db.execute(
        stmt.on_conflict_do_update(
            constraint="uq_institution_settings_institution",
            set_={column: value, "updated_by": actor.user_id},
        )
    )


async def update_notifications(
    db: AsyncSession, actor: Principal, patch: dict[str, Any]
) -> NotificationSettings:
    enforce(
        can_administer(actor, institution_id=actor.institution_id),
        action="settings.notifications.update",
        resource_type="settings",
    )
    before = (await load(db, actor.institution_id)).notifications
    try:
        after = NotificationSettings.model_validate({**before.model_dump(), **patch})
    except ValidationError as exc:
        raise InvalidInput(exc.errors()[0]["msg"]) from exc
    if after != before:
        await _save(db, actor, "notifications", after.model_dump())
        await _audit(
            db, actor, "settings.notifications.update", None, changes=_changes(before, after)
        )
    await db.commit()
    return after


async def update_safety(
    db: AsyncSession, actor: Principal, patch: dict[str, Any]
) -> SafetySettings:
    enforce(
        can_administer(actor, institution_id=actor.institution_id),
        action="settings.safety.update",
        resource_type="settings",
    )
    before = (await load(db, actor.institution_id)).safety
    try:
        after = SafetySettings.model_validate({**before.model_dump(), **patch})
    except ValidationError as exc:
        raise InvalidInput(exc.errors()[0]["msg"]) from exc
    if after != before:
        await _save(db, actor, "safety", after.model_dump())
        await _audit(db, actor, "settings.safety.update", None, changes=_changes(before, after))
    await db.commit()
    return after


# ---- crisis contacts ------------------------------------------------------------------------


async def list_contacts(db: AsyncSession, actor: Principal) -> list[m.CrisisContact]:
    """Active and inactive contacts of this institution, plus the national ones (read only)."""
    stmt = (
        select(m.CrisisContact)
        .where(
            or_(
                m.CrisisContact.institution_id.is_(None),
                m.CrisisContact.institution_id == actor.institution_id,
            )
        )
        .order_by(m.CrisisContact.sort_order, m.CrisisContact.label)
    )
    return list(await db.scalars(stmt))


async def _own_contact(
    db: AsyncSession, actor: Principal, contact_id: uuid.UUID, action: str
) -> m.CrisisContact:
    contact = await db.get(m.CrisisContact, contact_id)
    if contact is None:
        raise NotFound
    enforce(
        can_edit_resource(actor, resource_institution_id=contact.institution_id),
        action=action,
        resource_type="crisis_contact",
        resource_id=contact_id,
    )
    return contact


async def _other_active_emergency(
    db: AsyncSession, actor: Principal, excluding: uuid.UUID | None
) -> bool:
    stmt = select(func.count()).where(
        or_(
            m.CrisisContact.institution_id.is_(None),
            m.CrisisContact.institution_id == actor.institution_id,
        ),
        m.CrisisContact.kind == CrisisContactKind.EMERGENCY,
        m.CrisisContact.is_active.is_(True),
    )
    if excluding is not None:
        stmt = stmt.where(m.CrisisContact.id != excluding)
    return bool(await db.scalar(stmt))


def _check_reachable(phone: str | None, url: str | None, description: str | None) -> None:
    if not (phone or url or description):
        raise InvalidInput("add a phone number, a link or a short description")
    if url is not None and not url.startswith("https://"):
        raise InvalidInput("links must start with https://")


async def create_contact(
    db: AsyncSession, actor: Principal, data: dict[str, Any]
) -> m.CrisisContact:
    enforce(
        can_administer(actor, institution_id=actor.institution_id),
        action="crisis_contact.create",
        resource_type="crisis_contact",
    )
    _check_reachable(data.get("phone"), data.get("url"), data.get("description"))
    contact = m.CrisisContact(institution_id=actor.institution_id, **data)
    db.add(contact)
    await db.flush()
    await _audit(db, actor, "crisis_contact.create", contact.id, kind=contact.kind.value)
    await db.commit()
    return contact


async def update_contact(
    db: AsyncSession, actor: Principal, contact_id: uuid.UUID, patch: dict[str, Any]
) -> m.CrisisContact:
    contact = await _own_contact(db, actor, contact_id, "crisis_contact.update")
    was_active_emergency = contact.kind is CrisisContactKind.EMERGENCY and contact.is_active
    for key, value in patch.items():
        setattr(contact, key, value)
    _check_reachable(contact.phone, contact.url, contact.description)
    still_active_emergency = contact.kind is CrisisContactKind.EMERGENCY and contact.is_active
    if (
        was_active_emergency
        and not still_active_emergency
        and not await _other_active_emergency(db, actor, contact_id)
    ):
        await db.rollback()
        raise InvalidInput("at least one emergency contact must stay active")
    await _audit(
        db, actor, "crisis_contact.update", contact.id, fields=",".join(sorted(patch))[:190]
    )
    await db.commit()
    return contact


async def delete_contact(db: AsyncSession, actor: Principal, contact_id: uuid.UUID) -> None:
    contact = await _own_contact(db, actor, contact_id, "crisis_contact.delete")
    if contact.kind is CrisisContactKind.EMERGENCY and not await _other_active_emergency(
        db, actor, contact_id
    ):
        raise InvalidInput("at least one emergency contact must stay active")
    await db.delete(contact)
    await _audit(db, actor, "crisis_contact.delete", contact_id, kind=contact.kind.value)
    await db.commit()
