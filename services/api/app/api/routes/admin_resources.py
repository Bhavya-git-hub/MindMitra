"""Administrator endpoints for the self-help resource library."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.api.schemas import admin as s
from app.application import admin_resources as r
from app.domain.auth.permissions import Permission
from app.domain.auth.policies import Principal
from app.infrastructure.db.enums import ResourceType

router = APIRouter(prefix="/admin/resources", tags=["admin"])
Db = Annotated[AsyncSession, Depends(get_db)]
Manager = Annotated[Principal, Depends(require_permission(Permission.RESOURCE_MANAGE))]


def _draft(body: s.ResourceIn) -> r.ResourceDraft:
    return r.ResourceDraft(
        title=body.title,
        summary=body.summary,
        resource_type=ResourceType(body.resource_type),
        body=body.body,
        url=body.url,
        tags=body.tags,
        language=body.language,
        duration_minutes=body.duration_minutes,
    )


@router.get("")
async def list_resources(
    db: Db,
    principal: Manager,
    resource_type: ResourceType | None = None,
    published: bool | None = None,
    source: Literal["global", "institution"] | None = None,
    q: Annotated[str | None, Query(max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[s.ResourceOut]:
    rows = await r.list_resources(
        db,
        principal,
        resource_type=resource_type,
        published=published,
        source=source,
        query=q,
        limit=limit,
    )
    return [s.resource_out(x) for x in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_resource(body: s.ResourceIn, db: Db, principal: Manager) -> s.ResourceOut:
    row = await r.create_resource(db, principal, _draft(body), publish=body.publish)
    return s.resource_out(row)


@router.get("/{resource_id}")
async def get_resource(resource_id: uuid.UUID, db: Db, principal: Manager) -> s.ResourceOut:
    return s.resource_out(await r.get_resource(db, principal, resource_id))


@router.put("/{resource_id}")
async def update_resource(
    resource_id: uuid.UUID, body: s.ResourceIn, db: Db, principal: Manager
) -> s.ResourceOut:
    return s.resource_out(await r.update_resource(db, principal, resource_id, _draft(body)))


@router.patch("/{resource_id}/publication")
async def set_publication(
    resource_id: uuid.UUID, body: s.PublishIn, db: Db, principal: Manager
) -> s.ResourceOut:
    row = await r.set_published(db, principal, resource_id, published=body.published)
    return s.resource_out(row)


@router.delete("/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resource(resource_id: uuid.UUID, db: Db, principal: Manager) -> Response:
    await r.delete_resource(db, principal, resource_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
