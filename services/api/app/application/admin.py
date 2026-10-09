"""Administrator use cases: accounts, institution configuration, audit metadata.

Administrators manage *accounts*, never clinical content: nothing here reads notes, messages,
journals, AI conversations or wellness records (CLAUDE.md section 3).
"""

import dataclasses
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.access import NotFound, enforce
from app.application.auth.delivery import TokenDelivery
from app.application.auth.errors import Conflict, RegistrationRejected
from app.application.auth.service import EMAIL_RE, AuthService, normalise_email
from app.domain.auth.policies import Principal, can_manage_user
from app.infrastructure.db import models as m
from app.infrastructure.db.audit import append_audit_event
from app.infrastructure.db.enums import (
    AuditOutcome,
    OneTimeTokenPurpose,
    SessionRevokeReason,
    UserRole,
    UserStatus,
)
from app.infrastructure.db.ids import uuid7

MAX_LIMIT = 200


@dataclasses.dataclass(frozen=True)
class NewUser:
    email: str
    full_name: str
    role: UserRole
    department_code: str | None = None
    student_number: str | None = None
    enrollment_year: int | None = None
    year_of_study: int | None = None
    employee_number: str | None = None
    licence_number: str | None = None


async def _audit(
    db: AsyncSession,
    actor: Principal,
    action: str,
    *,
    resource_type: str,
    resource_id: uuid.UUID | None,
    details: dict[str, str] | None = None,
) -> None:
    await append_audit_event(
        db,
        institution_id=actor.institution_id,
        actor_id=actor.user_id,
        actor_role=UserRole.ADMINISTRATOR,
        action=action,
        outcome=AuditOutcome.ALLOWED,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
    )


async def list_users(
    db: AsyncSession,
    actor: Principal,
    *,
    role: UserRole | None,
    status: UserStatus | None,
    limit: int,
) -> list[m.User]:
    stmt = select(m.User).where(
        m.User.institution_id == actor.institution_id, m.User.deleted_at.is_(None)
    )
    if role is not None:
        stmt = stmt.where(m.User.role == role)
    if status is not None:
        stmt = stmt.where(m.User.status == status)
    return list(await db.scalars(stmt.order_by(m.User.created_at).limit(min(limit, MAX_LIMIT))))


async def _department(db: AsyncSession, actor: Principal, code: str | None) -> m.Department:
    if not code:
        raise RegistrationRejected("department_code is required for this role")
    dept = await db.scalar(
        select(m.Department).where(
            m.Department.institution_id == actor.institution_id,
            m.Department.code == code.strip().upper(),
        )
    )
    if dept is None:
        raise RegistrationRejected("unknown department code")
    return dept


async def create_user(
    db: AsyncSession, actor: Principal, data: NewUser, *, auth: AuthService, delivery: TokenDelivery
) -> m.User:
    """Create an invited account; the person sets their own password via an e-mailed link."""
    email = normalise_email(data.email)
    if not EMAIL_RE.match(email):
        raise RegistrationRejected("email address is not valid")
    user = m.User(
        id=uuid7(),
        institution_id=actor.institution_id,
        email=email,
        full_name=data.full_name.strip(),
        role=data.role,
        status=UserStatus.INVITED,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict("a user with this email already exists") from exc

    if data.role is UserRole.STUDENT:
        dept = await _department(db, actor, data.department_code)
        if not (data.student_number and data.enrollment_year and data.year_of_study):
            raise RegistrationRejected(
                "student_number, enrollment_year and year_of_study are required for students"
            )
        db.add(
            m.Student(
                user_id=user.id,
                institution_id=actor.institution_id,
                department_id=dept.id,
                student_number=data.student_number.strip(),
                enrollment_year=data.enrollment_year,
                year_of_study=data.year_of_study,
            )
        )
    elif data.role is UserRole.TEACHER:
        dept = await _department(db, actor, data.department_code)
        if not data.employee_number:
            raise RegistrationRejected("employee_number is required for teachers")
        db.add(
            m.Teacher(
                user_id=user.id,
                institution_id=actor.institution_id,
                department_id=dept.id,
                employee_number=data.employee_number.strip(),
            )
        )
    elif data.role is UserRole.THERAPIST:
        if not data.licence_number:
            raise RegistrationRejected("licence_number is required for therapists")
        db.add(
            m.Therapist(
                user_id=user.id,
                institution_id=actor.institution_id,
                licence_number=data.licence_number.strip(),
            )
        )
    else:  # institution admins only; platform admins are not created through the API
        db.add(m.Administrator(user_id=user.id, institution_id=actor.institution_id))
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict("a profile with this number already exists") from exc

    token = await auth.issue_account_setup(user)
    await _audit(
        db,
        actor,
        "user.create",
        resource_type="user",
        resource_id=user.id,
        details={"role": data.role.value},
    )
    await db.commit()
    await delivery.send(
        user_id=user.id, email=email, purpose=OneTimeTokenPurpose.ACCOUNT_SETUP, token=token
    )
    return user


async def set_user_status(
    db: AsyncSession, actor: Principal, user_id: uuid.UUID, status: UserStatus, *, auth: AuthService
) -> m.User:
    user = await db.get(m.User, user_id, with_for_update=True)
    if user is None or user.deleted_at is not None:
        raise NotFound
    enforce(
        can_manage_user(actor, target_user_id=user.id, target_institution_id=user.institution_id),
        action="user.update_status",
        resource_type="user",
        resource_id=user.id,
    )
    old = user.status
    user.status = status
    if status is not UserStatus.ACTIVE:
        await auth.revoke_user_sessions(user.id, SessionRevokeReason.ACCOUNT_DISABLED)
    await _audit(
        db,
        actor,
        "user.update_status",
        resource_type="user",
        resource_id=user.id,
        details={"from": old.value, "to": status.value},
    )
    await db.commit()
    return user


async def get_institution(db: AsyncSession, actor: Principal) -> m.Institution:
    inst = await db.get(m.Institution, actor.institution_id)
    if inst is None:
        raise NotFound
    return inst


async def update_institution(
    db: AsyncSession, actor: Principal, *, name: str | None, email_domains: list[str] | None
) -> m.Institution:
    inst = await db.get(m.Institution, actor.institution_id, with_for_update=True)
    if inst is None:
        raise NotFound
    changed: list[str] = []
    if name is not None:
        inst.name = name.strip()
        changed.append("name")
    if email_domains is not None:
        inst.email_domains = sorted({d.strip().lower() for d in email_domains if d.strip()})
        changed.append("email_domains")
    await _audit(
        db,
        actor,
        "institution.update",
        resource_type="institution",
        resource_id=inst.id,
        details={"fields": ",".join(changed)},
    )
    await db.commit()
    return inst


async def audit_events(
    db: AsyncSession,
    actor: Principal,
    *,
    action: str | None,
    before_seq: int | None,
    limit: int,
) -> list[m.AuditLog]:
    """Audit metadata for the admin's own institution (who did what, when; never content)."""
    stmt = select(m.AuditLog).where(m.AuditLog.institution_id == actor.institution_id)
    if action:
        stmt = stmt.where(m.AuditLog.action == action)
    if before_seq is not None:
        stmt = stmt.where(m.AuditLog.seq < before_seq)
    return list(await db.scalars(stmt.order_by(m.AuditLog.seq.desc()).limit(min(limit, MAX_LIMIT))))
