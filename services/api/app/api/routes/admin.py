"""Administrator endpoints: users, institution configuration, audit metadata.

Admins manage accounts and settings. They have no route to therapy notes, messages, journals,
wellness records or AI conversations, and the role grants no permission that would reach them.
"""

import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import app_state, get_auth_service, get_db, require_permission
from app.application import admin
from app.application.auth.service import AuthService
from app.domain.auth.permissions import Permission
from app.domain.auth.policies import Principal
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import UserRole, UserStatus

router = APIRouter(prefix="/admin", tags=["admin"])
Db = Annotated[AsyncSession, Depends(get_db)]
Auth = Annotated[AuthService, Depends(get_auth_service)]
UserManager = Annotated[Principal, Depends(require_permission(Permission.USER_MANAGE))]


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    status: str
    created_at: dt.datetime
    last_login_at: dt.datetime | None


class UserCreateIn(BaseModel):
    email: str = Field(max_length=320)
    full_name: str = Field(min_length=1, max_length=200)
    role: Literal["student", "teacher", "therapist", "administrator"]
    department_code: str | None = Field(default=None, max_length=20)
    student_number: str | None = Field(default=None, max_length=40)
    enrollment_year: int | None = Field(default=None, ge=1990, le=2100)
    year_of_study: int | None = Field(default=None, ge=1, le=8)
    employee_number: str | None = Field(default=None, max_length=40)
    licence_number: str | None = Field(default=None, max_length=60)


class UserStatusIn(BaseModel):
    status: Literal["active", "suspended", "deactivated"]


class InstitutionOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    region: str
    email_domains: list[str]


class InstitutionPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    email_domains: list[str] | None = Field(default=None, max_length=20)


class AuditEventOut(BaseModel):
    seq: int
    occurred_at: dt.datetime
    actor_id: uuid.UUID | None
    actor_role: str | None
    action: str
    outcome: str
    resource_type: str | None
    resource_id: uuid.UUID | None
    subject_student_id: uuid.UUID | None
    reason: str | None
    details: dict[str, Any]


def _user_out(u: m.User) -> UserOut:
    return UserOut(
        id=u.id,
        email=u.email,
        full_name=u.full_name,
        role=u.role.value,
        status=u.status.value,
        created_at=u.created_at,
        last_login_at=u.last_login_at,
    )


def _institution_out(i: m.Institution) -> InstitutionOut:
    return InstitutionOut(
        id=i.id, name=i.name, slug=i.slug, region=i.region, email_domains=list(i.email_domains)
    )


@router.get("/users")
async def list_users(
    db: Db,
    principal: UserManager,
    role: UserRole | None = None,
    user_status: Annotated[UserStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[UserOut]:
    rows = await admin.list_users(db, principal, role=role, status=user_status, limit=limit)
    return [_user_out(u) for u in rows]


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreateIn, request: Request, db: Db, auth: Auth, principal: UserManager
) -> UserOut:
    user = await admin.create_user(
        db,
        principal,
        admin.NewUser(
            email=body.email,
            full_name=body.full_name,
            role=UserRole(body.role),
            department_code=body.department_code,
            student_number=body.student_number,
            enrollment_year=body.enrollment_year,
            year_of_study=body.year_of_study,
            employee_number=body.employee_number,
            licence_number=body.licence_number,
        ),
        auth=auth,
        delivery=app_state(request).delivery,
    )
    return _user_out(user)


@router.patch("/users/{user_id}")
async def set_user_status(
    user_id: uuid.UUID, body: UserStatusIn, db: Db, auth: Auth, principal: UserManager
) -> UserOut:
    user = await admin.set_user_status(db, principal, user_id, UserStatus(body.status), auth=auth)
    return _user_out(user)


@router.get("/config")
async def get_config(
    db: Db,
    principal: Annotated[Principal, Depends(require_permission(Permission.CONFIG_MANAGE))],
) -> InstitutionOut:
    return _institution_out(await admin.get_institution(db, principal))


@router.patch("/config")
async def update_config(
    body: InstitutionPatchIn,
    db: Db,
    principal: Annotated[Principal, Depends(require_permission(Permission.CONFIG_MANAGE))],
) -> InstitutionOut:
    inst = await admin.update_institution(
        db, principal, name=body.name, email_domains=body.email_domains
    )
    return _institution_out(inst)


@router.get("/audit")
async def audit_log(
    db: Db,
    principal: Annotated[Principal, Depends(require_permission(Permission.AUDIT_READ))],
    action: Annotated[str | None, Query(max_length=80)] = None,
    before_seq: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AuditEventOut]:
    rows = await admin.audit_events(
        db, principal, action=action, before_seq=before_seq, limit=limit
    )
    return [
        AuditEventOut(
            seq=r.seq,
            occurred_at=r.occurred_at,
            actor_id=r.actor_id,
            actor_role=r.actor_role.value if r.actor_role else None,
            action=r.action,
            outcome=r.outcome.value,
            resource_type=r.resource_type,
            resource_id=r.resource_id,
            subject_student_id=r.subject_student_id,
            reason=r.reason,
            details=r.details,
        )
        for r in rows
    ]
