"""A student asks one of their own teachers for help. The student chooses who, and may withdraw."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.api.schemas import teacher as s
from app.application import teacher_support
from app.domain.auth.permissions import Permission
from app.domain.auth.policies import Principal

router = APIRouter(prefix="/me/teacher-support", tags=["student"])
Db = Annotated[AsyncSession, Depends(get_db)]


def _guard(permission: Permission) -> Any:
    return Depends(require_permission(permission))


Asker = Annotated[Principal, _guard(Permission.TEACHER_SUPPORT_REQUEST)]


@router.get("/options")
async def options(db: Db, principal: Asker) -> list[s.CourseOptionOut]:
    """The student's own courses and who teaches them."""
    return [s.course_option_out(c) for c in await teacher_support.my_courses(db, principal)]


@router.get("")
async def list_requests(db: Db, principal: Asker) -> list[s.SupportRequestOut]:
    return [s.support_request_out(v) for v in await teacher_support.list_mine(db, principal)]


@router.post("", status_code=201)
async def create_request(body: s.SupportRequestIn, db: Db, principal: Asker) -> s.SupportRequestOut:
    view = await teacher_support.create(
        db,
        principal,
        course_id=body.course_id,
        teacher_id=body.teacher_id,
        topic=body.topic,
        message=body.message,
    )
    return s.support_request_out(view)


@router.post("/{request_id}/withdraw")
async def withdraw_request(request_id: uuid.UUID, db: Db, principal: Asker) -> s.SupportRequestOut:
    return s.support_request_out(await teacher_support.withdraw(db, principal, request_id))
