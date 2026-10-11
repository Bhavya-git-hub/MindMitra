"""Request dependencies: database session, authentication, role and permission guards.

Layered checks (SECURITY_ARCHITECTURE.md 4.1):

1. ``get_principal`` - the access JWT is valid *and* its session is live in the database,
   and the user is still active with the same role. A token alone is never enough, so logout,
   deactivation and role changes take effect on the very next request.
2. ``require_roles`` / ``require_permission`` - the route guard ("role middleware" and
   "authorization middleware"). Every non-public route declares one; a test enforces it.
3. Resource policies (``app/domain/auth/policies.py``) inside the use case decide whether
   this caller may see *this* record.

Denials at layers 2 and 3 are written to the audit log in their own transaction, so a
rolled-back request still leaves a trace.
"""

import dataclasses
import datetime as dt
import logging
import math
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.rate_limit import SlidingWindowRateLimiter
from app.application.auth.delivery import TokenDelivery
from app.application.auth.service import AuthService
from app.core.access_tokens import AccessTokenCodec, InvalidAccessToken
from app.core.config import Settings
from app.core.crypto import keyed_hash
from app.domain.auth.permissions import Permission, Role, has_permission
from app.domain.auth.policies import Principal
from app.infrastructure.db import models as m
from app.infrastructure.db.audit import append_audit_event
from app.infrastructure.db.enums import AuditOutcome, UserRole, UserStatus
from app.infrastructure.ml_client import CompanionClient, IndicatorClient
from app.infrastructure.notifications.providers import Providers
from app.infrastructure.realtime_hub import Hub

log = logging.getLogger("mindmitra.authz")

# Attribute set on every guard dependency; the route-coverage test looks for it.
AUTHZ_MARKER = "__mindmitra_authz__"


@dataclasses.dataclass
class AppState:
    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]
    codec: AccessTokenCodec
    delivery: TokenDelivery
    limiter: SlidingWindowRateLimiter
    hub: Hub
    providers: Providers
    # The AI service client, or None when ML_SERVICE_URL is not set (companion unavailable).
    companion: CompanionClient | None = None
    # The same service's wellness indicators (None when not configured: answered with 503).
    indicators: IndicatorClient | None = None
    companion_limiter: SlidingWindowRateLimiter = dataclasses.field(
        default_factory=lambda: SlidingWindowRateLimiter(8)
    )


def app_state(request: Request) -> AppState:
    state: AppState = request.app.state.mm
    return state


def get_indicator_client(request: Request) -> IndicatorClient | None:
    return app_state(request).indicators


def client_ip(request: Request) -> str | None:
    # X-Forwarded-For is only trustworthy behind a known proxy; that is configured at deploy.
    return request.client.host if request.client else None


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """One session per request. Use cases commit explicitly; anything else is rolled back."""
    async with app_state(request).session_factory() as session:
        try:
            yield session
        finally:
            if session.in_transaction():
                await session.rollback()


def get_auth_service(request: Request, db: Annotated[AsyncSession, Depends(get_db)]) -> AuthService:
    st = app_state(request)
    return AuthService(db, settings=st.settings, codec=st.codec, delivery=st.delivery)


def _unauthorized() -> HTTPException:
    return HTTPException(401, "Authentication required.", headers={"WWW-Authenticate": "Bearer"})


_bearer = HTTPBearer(auto_error=False)


async def principal_from_token(
    db: AsyncSession, codec: AccessTokenCodec, token: str
) -> Principal | None:
    """The signed-in user behind an access token, or None. The token must be valid *and* its
    session live, the user active and the role unchanged. Used by HTTP routes and WebSockets."""
    try:
        claims = codec.decode(token)
    except InvalidAccessToken:
        return None
    row = (
        await db.execute(
            select(
                m.AuthSession.user_id,
                m.AuthSession.institution_id,
                m.AuthSession.revoked_at,
                m.AuthSession.absolute_expires_at,
                m.User.role,
                m.User.status,
                m.User.deleted_at,
            )
            .join(m.User, m.User.id == m.AuthSession.user_id)
            .where(m.AuthSession.id == claims.session_id)
        )
    ).first()
    now = dt.datetime.now(dt.UTC)
    if (
        row is None
        or row.user_id != claims.user_id
        or row.institution_id != claims.institution_id
        or row.revoked_at is not None
        or row.absolute_expires_at <= now
        or row.status is not UserStatus.ACTIVE
        or row.deleted_at is not None
        or row.role.value != claims.role  # role changed since the token was issued
    ):
        return None
    return Principal(
        user_id=claims.user_id,
        institution_id=claims.institution_id,
        role=Role(row.role.value),
        session_id=claims.session_id,
    )


async def get_principal(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    if creds is None:
        raise _unauthorized()
    principal = await principal_from_token(db, app_state(request).codec, creds.credentials)
    if principal is None:
        raise _unauthorized()
    request.state.principal = principal
    return principal


async def audit_denial(
    request: Request,
    principal: Principal,
    *,
    action: str,
    reason: str,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    subject_student_id: uuid.UUID | None = None,
) -> None:
    """Record a denied access attempt in its own transaction. Never masks the denial."""
    st = app_state(request)
    ip = client_ip(request)
    try:
        async with st.session_factory() as s:
            await append_audit_event(
                s,
                institution_id=principal.institution_id,
                actor_id=principal.user_id,
                actor_role=UserRole(principal.role.value),
                action=action,
                outcome=AuditOutcome.DENIED,
                reason=reason,
                resource_type=resource_type,
                resource_id=resource_id,
                subject_student_id=subject_student_id,
                request_id=getattr(request.state, "request_id", None),
                ip_hash=keyed_hash(st.settings.field_encryption_key.get_secret_value(), "ip", ip)
                if ip
                else None,
            )
            await s.commit()
    except Exception:  # pragma: no cover - audit outage must not turn a deny into an allow
        log.exception("failed to write denial audit event")


def _mark(dep: Callable[..., Any], description: str) -> Callable[..., Any]:
    setattr(dep, AUTHZ_MARKER, description)
    return dep


def authenticated() -> Callable[..., Awaitable[Principal]]:
    """Any signed-in user (used only where every role is genuinely allowed, e.g. logout)."""

    async def dependency(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        return principal

    return _mark(dependency, "authenticated")


def require_roles(*roles: Role) -> Callable[..., Awaitable[Principal]]:
    """Role middleware: the caller's current role must be one of ``roles``."""
    allowed = frozenset(roles)

    async def dependency(
        request: Request, principal: Annotated[Principal, Depends(get_principal)]
    ) -> Principal:
        if principal.role not in allowed:
            await audit_denial(
                request, principal, action=f"route:{request.url.path}", reason="role_not_allowed"
            )
            raise HTTPException(403, "You do not have access to this resource.")
        return principal

    return _mark(dependency, "roles:" + ",".join(sorted(r.value for r in roles)))


def require_permission(*permissions: Permission) -> Callable[..., Awaitable[Principal]]:
    """Authorization middleware: the caller's role must grant every listed permission."""

    async def dependency(
        request: Request, principal: Annotated[Principal, Depends(get_principal)]
    ) -> Principal:
        missing = [p for p in permissions if not has_permission(principal.role, p)]
        if missing:
            await audit_denial(
                request,
                principal,
                action=f"permission:{missing[0].value}",
                reason="missing_permission",
            )
            raise HTTPException(403, "You do not have access to this resource.")
        return principal

    return _mark(dependency, "permissions:" + ",".join(p.value for p in permissions))


def rate_limited(bucket: str) -> Callable[..., Awaitable[None]]:
    async def dependency(request: Request) -> None:
        retry = app_state(request).limiter.hit(f"{bucket}:{client_ip(request) or 'unknown'}")
        if retry is not None:
            raise HTTPException(
                429,
                "Too many requests. Please wait a moment and try again.",
                headers={"Retry-After": str(max(1, math.ceil(retry)))},
            )

    return dependency
