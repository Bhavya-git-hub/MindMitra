"""FastAPI application factory.

Every route except those in ``PUBLIC_ROUTES`` declares an authorization guard from
``app.api.deps``; ``tests/test_route_authz.py`` fails the build if one is missing.
"""

import datetime as dt
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.deps import AppState, audit_denial
from app.api.problems import install_problem_handlers, problem
from app.api.rate_limit import SlidingWindowRateLimiter
from app.api.routes import admin, auth, care, health, insights, me
from app.application.access import AccessDenied, NotFound
from app.application.auth.delivery import InMemoryTokenOutbox, TokenDelivery
from app.application.auth.errors import (
    Conflict,
    CsrfFailed,
    InvalidCredentials,
    InvalidToken,
    PasswordRejected,
    RegistrationRejected,
)
from app.application.care import InvalidTransition
from app.core.access_tokens import AccessTokenCodec, load_private_key
from app.core.config import Settings, get_settings
from app.domain.auth.policies import Principal
from app.infrastructure.db.session import create_engine, create_session_factory

API_PREFIX = "/api/v1"

# (method, path) pairs reachable without signing in. Anything else must carry a guard.
PUBLIC_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", f"{API_PREFIX}/health/live"),
        ("POST", f"{API_PREFIX}/auth/register"),
        ("POST", f"{API_PREFIX}/auth/verify-email"),
        ("POST", f"{API_PREFIX}/auth/login"),
        ("POST", f"{API_PREFIX}/auth/refresh"),
        ("POST", f"{API_PREFIX}/auth/password/forgot"),
        ("POST", f"{API_PREFIX}/auth/password/reset"),
    }
)

ROUTERS = (health.router, auth.router, me.router, care.router, insights.router, admin.router)

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
}


def _default_delivery(settings: Settings) -> TokenDelivery:
    if settings.app_env in ("development", "test"):
        return InMemoryTokenOutbox()
    raise RuntimeError(
        "No e-mail sender is configured for one-time tokens; refusing to start outside "
        "development/test (tokens would otherwise be lost or logged)."
    )


def create_app(
    settings: Settings | None = None,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    delivery: TokenDelivery | None = None,
    limiter: SlidingWindowRateLimiter | None = None,
) -> FastAPI:
    s = settings or get_settings()
    engine: AsyncEngine | None = None
    if session_factory is None:
        engine = create_engine(s)
        session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if engine is not None:
            await engine.dispose()

    app = FastAPI(
        title="MindMitra API",
        version="0.1.0",
        lifespan=lifespan,
        # Interactive docs only where there is no real data.
        docs_url="/docs" if s.app_env in ("development", "test") else None,
        redoc_url=None,
        openapi_url="/openapi.json" if s.app_env in ("development", "test") else None,
    )
    app.state.mm = AppState(
        settings=s,
        session_factory=session_factory,
        codec=AccessTokenCodec(
            load_private_key(s.jwt_private_key.get_secret_value()),
            issuer=s.jwt_issuer,
            audience=s.jwt_audience,
            ttl=dt.timedelta(seconds=s.access_token_ttl_seconds),
        ),
        delivery=delivery or _default_delivery(s),
        limiter=limiter or SlidingWindowRateLimiter(s.auth_rate_limit_per_minute),
    )

    install_problem_handlers(app)
    _install_domain_handlers(app)

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    if s.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=s.cors_origin_list,
            allow_credentials=True,  # the refresh cookie
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Request-ID"],
            expose_headers=["X-Request-ID", "Retry-After"],
        )

    for router in ROUTERS:
        app.include_router(router, prefix=API_PREFIX)
    return app


def _install_domain_handlers(app: FastAPI) -> None:
    @app.exception_handler(AccessDenied)
    async def _denied(request: Request, exc: AccessDenied) -> JSONResponse:
        principal: Principal | None = getattr(request.state, "principal", None)
        if principal is not None:
            await audit_denial(
                request,
                principal,
                action=exc.action,
                reason=exc.decision.reason,
                resource_type=exc.resource_type,
                resource_id=exc.resource_id,
                subject_student_id=exc.subject_student_id,
            )
        if exc.decision.hide:
            return problem(request, 404, "Not found.")
        return problem(request, 403, "You do not have access to this resource.")

    @app.exception_handler(NotFound)
    async def _not_found(request: Request, exc: NotFound) -> JSONResponse:
        return problem(request, 404, "Not found.")

    @app.exception_handler(InvalidCredentials)
    async def _bad_login(request: Request, exc: InvalidCredentials) -> JSONResponse:
        return problem(
            request, 401, "Invalid email or password.", headers={"WWW-Authenticate": "Bearer"}
        )

    @app.exception_handler(InvalidToken)
    async def _bad_token(request: Request, exc: InvalidToken) -> JSONResponse:
        return problem(request, 401, "The link or token is invalid or has expired.")

    @app.exception_handler(CsrfFailed)
    async def _csrf(request: Request, exc: CsrfFailed) -> JSONResponse:
        return problem(request, 403, "Missing or invalid CSRF token.")

    @app.exception_handler(PasswordRejected)
    async def _weak(request: Request, exc: PasswordRejected) -> JSONResponse:
        errors = [{"loc": ["body", "password"], "msg": p} for p in exc.problems]
        return problem(request, 422, "The password does not meet the policy.", errors=errors)

    @app.exception_handler(RegistrationRejected)
    async def _reg(request: Request, exc: RegistrationRejected) -> JSONResponse:
        return problem(request, 422, str(exc) or "Registration details are not valid.")

    @app.exception_handler(Conflict)
    async def _conflict(request: Request, exc: Conflict) -> JSONResponse:
        return problem(request, 409, str(exc) or "Conflict.")

    @app.exception_handler(InvalidTransition)
    async def _transition(request: Request, exc: InvalidTransition) -> JSONResponse:
        return problem(request, 409, str(exc))
