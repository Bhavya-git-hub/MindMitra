"""Consents, privacy history, a copy of one's data, and asking for a person to reach out."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import app_state, get_db, require_permission
from app.api.schemas import student as s
from app.application import privacy, safety, safety_workflow
from app.domain.auth.permissions import Permission
from app.domain.auth.policies import Principal
from app.domain.safety.guidance import DISCLAIMER
from app.infrastructure.db.enums import ConsentScope

router = APIRouter(prefix="/me", tags=["student"])
Db = Annotated[AsyncSession, Depends(get_db)]
ConsentManager = Annotated[Principal, Depends(require_permission(Permission.CONSENT_MANAGE_OWN))]
PrivacyReader = Annotated[Principal, Depends(require_permission(Permission.PRIVACY_READ_OWN))]
HelpRequester = Annotated[Principal, Depends(require_permission(Permission.SUPPORT_REQUEST_CREATE))]


def _consent_out(c: privacy.ConsentState) -> s.ConsentOut:
    return s.ConsentOut(
        scope=c.info.scope.value,
        title=c.info.title,
        description=c.info.description,
        required=c.info.required,
        granted=c.granted,
        granted_at=c.granted_at,
        policy_version=c.policy_version,
    )


@router.get("/consents")
async def list_consents(db: Db, principal: ConsentManager) -> list[s.ConsentOut]:
    return [_consent_out(c) for c in await privacy.list_consents(db, principal)]


@router.put("/consents/{scope}")
async def put_consent(
    scope: ConsentScope,
    body: s.ConsentPutIn,
    request: Request,
    db: Db,
    principal: ConsentManager,
) -> s.ConsentOut:
    state = await privacy.set_consent(
        db, principal, scope, body.granted, app_state(request).settings
    )
    return _consent_out(state)


@router.get("/privacy/access-history")
async def access_history(
    db: Db, principal: PrivacyReader, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[s.AccessEventOut]:
    events = await privacy.access_history(db, principal, limit)
    return [
        s.AccessEventOut(
            occurred_at=e.occurred_at,
            actor_role=e.actor_role,
            action=e.action,
            resource_type=e.resource_type,
        )
        for e in events
    ]


@router.get("/privacy/export")
async def export_my_data(db: Db, principal: PrivacyReader) -> Response:
    data = await privacy.export_data(db, principal)
    return Response(
        content=json.dumps(data, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="mindmitra-my-data.json"'},
    )


@router.post("/support-requests", status_code=201)
async def create_support_request(
    body: s.SupportRequestIn, db: Db, principal: HelpRequester
) -> s.SupportRequestOut:
    result = await privacy.request_support(db, principal, body.message)
    return s.SupportRequestOut(
        id=result.alert.id,
        status=result.alert.status.value,
        already_open=result.already_open,
        reaches_care_team=result.assigned_to_care_team,
        created_at=result.alert.created_at,
    )


@router.get("/safety/status")
async def safety_status(db: Db, principal: HelpRequester) -> s.SafetyStatusOut:
    """Whether normal suggestions are paused after a HIGH or IMMEDIATE concern, and the support
    to show meanwhile (ADR 0013)."""
    hold = await safety_workflow.active_hold(db, principal)
    support = (
        s.safety_out(await safety_workflow.hold_outcome(db, principal, hold)) if hold else None
    )
    return s.SafetyStatusOut(
        recommendations_paused=hold is not None,
        support=support,
        disclaimer=DISCLAIMER,
    )


@router.get("/safety/resources")
async def safety_resources(db: Db, principal: HelpRequester) -> list[s.CrisisContactOut]:
    rows = await safety.crisis_contacts(db, principal)
    return [
        s.CrisisContactOut(
            id=r.id,
            label=r.label,
            kind=r.kind.value,
            phone=r.phone,
            url=r.url,
            description=r.description,
            hours=r.hours,
        )
        for r in rows
    ]
