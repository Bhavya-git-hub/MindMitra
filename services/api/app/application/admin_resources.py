"""Administrator management of the self-help resource library.

Global resources (no institution) ship with the platform and are read-only here; the
institution's own resources can be written, published and withdrawn. Publishing records who
reviewed the item and when (the database refuses a published item without a review).
"""

import dataclasses
import re
import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.access import NotFound, enforce
from app.application.admin_common import LIKE_ESCAPE, MAX_LIMIT, audit, like
from app.application.directory import FACULTY_TAG
from app.application.errors import InvalidInput
from app.application.timeutil import now_utc
from app.domain.auth.policies import Principal, can_edit_resource
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import ResourceType
from app.infrastructure.db.ids import uuid7

TAG_RE = re.compile(r"^[a-z0-9][a-z0-9 -]{0,39}$")
MAX_TAGS = 10


@dataclasses.dataclass(frozen=True)
class ResourceDraft:
    title: str
    summary: str
    resource_type: ResourceType
    body: str | None = None
    url: str | None = None
    tags: list[str] = dataclasses.field(default_factory=list)
    language: str = "en"
    duration_minutes: int | None = None


def _text(value: str, what: str, limit: int) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise InvalidInput(f"{what} cannot be empty.")
    if len(cleaned) > limit:
        raise InvalidInput(f"{what} must be at most {limit} characters.")
    return cleaned


def _checked(draft: ResourceDraft) -> ResourceDraft:
    title = _text(draft.title, "The title", 200)
    summary = _text(draft.summary, "The summary", 500)
    body = draft.body.strip() if draft.body and draft.body.strip() else None
    if body is not None and len(body) > 20000:
        raise InvalidInput("The text must be at most 20,000 characters.")
    url = draft.url.strip() if draft.url and draft.url.strip() else None
    if url is not None and (not url.startswith("https://") or len(url) > 500 or " " in url):
        raise InvalidInput("The link must be a secure (https) address.")
    if body is None and url is None:
        raise InvalidInput("Add some text or a link.")
    tags = sorted({t.strip().lower() for t in draft.tags if t.strip()})
    if len(tags) > MAX_TAGS or any(not TAG_RE.match(t) for t in tags):
        raise InvalidInput("Use up to 10 short tags of letters, digits, spaces and hyphens.")
    language = draft.language.strip().lower()
    if not re.fullmatch(r"[a-z]{2,3}(-[a-z0-9]{2,8})?", language):
        raise InvalidInput("Use a language code like en or hi.")
    if draft.duration_minutes is not None and not 1 <= draft.duration_minutes <= 600:
        raise InvalidInput("Duration must be between 1 and 600 minutes.")
    return dataclasses.replace(
        draft, title=title, summary=summary, body=body, url=url, tags=tags, language=language
    )


def is_faculty(resource: m.Resource) -> bool:
    return FACULTY_TAG in resource.tags


async def list_resources(
    db: AsyncSession,
    actor: Principal,
    *,
    resource_type: ResourceType | None,
    published: bool | None,
    source: str | None,
    query: str | None,
    limit: int,
) -> list[m.Resource]:
    stmt = select(m.Resource)
    if source == "global":
        stmt = stmt.where(m.Resource.institution_id.is_(None))
    elif source == "institution":
        stmt = stmt.where(m.Resource.institution_id == actor.institution_id)
    else:
        stmt = stmt.where(
            or_(
                m.Resource.institution_id.is_(None),
                m.Resource.institution_id == actor.institution_id,
            )
        )
    if resource_type is not None:
        stmt = stmt.where(m.Resource.resource_type == resource_type)
    if published is not None:
        stmt = stmt.where(m.Resource.is_published.is_(published))
    if query and query.strip():
        pattern = like(query)
        stmt = stmt.where(
            or_(
                m.Resource.title.ilike(pattern, escape=LIKE_ESCAPE),
                m.Resource.summary.ilike(pattern, escape=LIKE_ESCAPE),
            )
        )
    rows = await db.scalars(
        stmt.order_by(m.Resource.is_published, m.Resource.title).limit(min(limit, MAX_LIMIT))
    )
    return list(rows)


async def _visible(db: AsyncSession, actor: Principal, resource_id: uuid.UUID) -> m.Resource:
    """Global resources and this institution's own; another institution's look absent."""
    row = await db.scalar(
        select(m.Resource).where(
            m.Resource.id == resource_id,
            or_(
                m.Resource.institution_id.is_(None),
                m.Resource.institution_id == actor.institution_id,
            ),
        )
    )
    if row is None:
        raise NotFound
    return row


async def get_resource(db: AsyncSession, actor: Principal, resource_id: uuid.UUID) -> m.Resource:
    return await _visible(db, actor, resource_id)


async def _editable(
    db: AsyncSession, actor: Principal, resource_id: uuid.UUID, action: str
) -> m.Resource:
    row = await _visible(db, actor, resource_id)
    enforce(
        can_edit_resource(actor, resource_institution_id=row.institution_id),
        action=action,
        resource_type="resource",
        resource_id=resource_id,
    )
    return row


def _apply(row: m.Resource, draft: ResourceDraft) -> None:
    row.title = draft.title
    row.summary = draft.summary
    row.body = draft.body
    row.url = draft.url
    row.resource_type = draft.resource_type
    row.tags = draft.tags
    row.language = draft.language
    row.duration_minutes = draft.duration_minutes


async def create_resource(
    db: AsyncSession, actor: Principal, draft: ResourceDraft, *, publish: bool
) -> m.Resource:
    clean = _checked(draft)
    row = m.Resource(id=uuid7(), institution_id=actor.institution_id, is_published=False)
    _apply(row, clean)
    if publish:
        row.is_published = True
        row.reviewed_by = actor.user_id
        row.reviewed_at = now_utc()
    db.add(row)
    await db.flush()
    await audit(
        db,
        actor,
        "resource.create",
        resource_type="resource",
        resource_id=row.id,
        published=publish,
    )
    await db.commit()
    return row


async def update_resource(
    db: AsyncSession, actor: Principal, resource_id: uuid.UUID, draft: ResourceDraft
) -> m.Resource:
    row = await _editable(db, actor, resource_id, "resource.update")
    _apply(row, _checked(draft))
    if row.is_published:  # an edit to live content is a fresh review by the editor
        row.reviewed_by = actor.user_id
        row.reviewed_at = now_utc()
    await audit(db, actor, "resource.update", resource_type="resource", resource_id=row.id)
    await db.commit()
    return row


async def set_published(
    db: AsyncSession, actor: Principal, resource_id: uuid.UUID, *, published: bool
) -> m.Resource:
    row = await _editable(db, actor, resource_id, "resource.publish")
    row.is_published = published
    if published:
        row.reviewed_by = actor.user_id
        row.reviewed_at = now_utc()
    await audit(
        db,
        actor,
        "resource.publish" if published else "resource.unpublish",
        resource_type="resource",
        resource_id=row.id,
    )
    await db.commit()
    return row


async def delete_resource(db: AsyncSession, actor: Principal, resource_id: uuid.UUID) -> None:
    row = await _editable(db, actor, resource_id, "resource.delete")
    await db.delete(row)
    await audit(db, actor, "resource.delete", resource_type="resource", resource_id=resource_id)
    await db.commit()
