"""Administrator endpoints: users, institution configuration, audit log, therapist verification.

Admins manage accounts and settings. They have no route to therapy notes, messages, journals,
wellness records or AI conversations, and the role grants no permission that would reach them.
Each route needs one specific admin permission, and the use case checks the target belongs to
the administrator's own institution.
"""

import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import app_state, get_auth_service, get_db, require_permission
from app.api.schemas import admin as s
from app.api.schemas import therapist as ther
from app.application import admin, admin_audit, therapist_profile
from app.application.auth.service import AuthService
from app.domain.auth.permissions import Permission
from app.domain.auth.policies import Principal
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import AuditOutcome, UserRole, UserStatus, VerificationStatus

router = APIRouter(prefix="/admin", tags=["admin"])
Db = Annotated[AsyncSession, Depends(get_db)]
Auth = Annotated[AuthService, Depends(get_auth_service)]


def _guard(permission: Permission) -> Any:
    return Depends(require_permission(permission))


UserManager = Annotated[Principal, _guard(Permission.USER_MANAGE)]
ConfigManager = Annotated[Principal, _guard(Permission.CONFIG_MANAGE)]
AuditReader = Annotated[Principal, _guard(Permission.AUDIT_READ)]
Verifier = Annotated[Principal, _guard(Permission.THERAPIST_VERIFY)]


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
    q: Annotated[str | None, Query(max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> s.Page[s.UserOut]:
    page = await admin.list_users(
        db, principal, role=role, status=user_status, query=q, limit=limit, offset=offset
    )
    return s.user_page(page)


@router.get("/users/{user_id}")
async def get_user(user_id: uuid.UUID, db: Db, principal: UserManager) -> s.UserOut:
    return s.user_out(await admin.get_user(db, principal, user_id))


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreateIn, request: Request, db: Db, auth: Auth, principal: UserManager
) -> s.UserOut:
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
    return s.user_out(user)


@router.patch("/users/{user_id}")
async def set_user_status(
    user_id: uuid.UUID, body: UserStatusIn, db: Db, auth: Auth, principal: UserManager
) -> s.UserOut:
    user = await admin.set_user_status(db, principal, user_id, UserStatus(body.status), auth=auth)
    return s.user_out(user)


@router.post("/users/{user_id}/resend-invite", status_code=status.HTTP_204_NO_CONTENT)
async def resend_invite(
    user_id: uuid.UUID, request: Request, db: Db, auth: Auth, principal: UserManager
) -> Response:
    await admin.resend_invite(
        db, principal, user_id, auth=auth, delivery=app_state(request).delivery
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/users/{user_id}/sign-out", status_code=status.HTTP_204_NO_CONTENT)
async def sign_out_everywhere(
    user_id: uuid.UUID, db: Db, auth: Auth, principal: UserManager
) -> Response:
    await admin.sign_out_everywhere(db, principal, user_id, auth=auth)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/config")
async def get_config(db: Db, principal: ConfigManager) -> InstitutionOut:
    return _institution_out(await admin.get_institution(db, principal))


@router.patch("/config")
async def update_config(
    body: InstitutionPatchIn, db: Db, principal: ConfigManager
) -> InstitutionOut:
    inst = await admin.update_institution(
        db, principal, name=body.name, email_domains=body.email_domains
    )
    return _institution_out(inst)


# ---- audit log -------------------------------------------------------------------------------


def _audit_filter(
    action: str | None,
    outcome: AuditOutcome | None,
    actor_id: uuid.UUID | None,
    resource_type: str | None,
    since: dt.datetime | None,
    until: dt.datetime | None,
) -> admin_audit.AuditFilter:
    return admin_audit.AuditFilter(
        action=action,
        outcome=outcome,
        actor_id=actor_id,
        resource_type=resource_type,
        since=since,
        until=until,
    )


@router.get("/audit")
async def audit_log(
    db: Db,
    principal: AuditReader,
    action: Annotated[str | None, Query(max_length=80)] = None,
    outcome: AuditOutcome | None = None,
    actor_id: uuid.UUID | None = None,
    resource_type: Annotated[str | None, Query(max_length=40)] = None,
    since: dt.datetime | None = None,
    until: dt.datetime | None = None,
    before_seq: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[s.AuditEventOut]:
    f = _audit_filter(action, outcome, actor_id, resource_type, since, until)
    rows = await admin_audit.list_events(db, principal, f, before_seq=before_seq, limit=limit)
    return [s.audit_event_out(r) for r in rows]


@router.get("/audit/actions")
async def audit_actions(db: Db, principal: AuditReader) -> list[str]:
    return await admin_audit.actions(db, principal)


@router.post("/audit/verify")
async def verify_audit_chain(db: Db, principal: AuditReader) -> s.ChainStatusOut:
    return s.chain_out(await admin_audit.verify(db, principal))


@router.get("/audit/export")
async def export_audit_log(
    db: Db,
    principal: AuditReader,
    action: Annotated[str | None, Query(max_length=80)] = None,
    outcome: AuditOutcome | None = None,
    actor_id: uuid.UUID | None = None,
    resource_type: Annotated[str | None, Query(max_length=40)] = None,
    since: dt.datetime | None = None,
    until: dt.datetime | None = None,
) -> Response:
    f = _audit_filter(action, outcome, actor_id, resource_type, since, until)
    body = await admin_audit.export_csv(db, principal, f)
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="audit-log.csv"'},
    )


# ---- professional verification (therapists) -------------------------------------------------


@router.get("/therapists")
async def therapists_for_review(
    db: Db, principal: Verifier, status: Literal["pending", "verified", "rejected"] | None = None
) -> list[ther.TherapistReviewOut]:
    rows = await therapist_profile.list_for_verification(
        db, principal, VerificationStatus(status) if status else None
    )
    return [ther.review_out(t, u) for t, u in rows]


@router.patch("/therapists/{therapist_id}/verification")
async def review_therapist(
    therapist_id: uuid.UUID, body: ther.VerificationReviewIn, db: Db, principal: Verifier
) -> ther.TherapistReviewOut:
    t, u = await therapist_profile.set_verification(
        db,
        principal,
        therapist_id,
        status=VerificationStatus(body.status),
        note=body.note,
        licence_expires_on=body.licence_expires_on,
    )
    return ther.review_out(t, u)
