"""Authentication endpoints (API_DESIGN.md 2.1).

Token transport:

* The **access token** (JWT, 10 min) is returned in the response body. Browsers keep it in
  memory and send it as ``Authorization: Bearer``; it is never put in a cookie, so ordinary
  API calls are not exposed to CSRF.
* The **refresh token** is set only as an ``HttpOnly; Secure; SameSite=Strict`` cookie scoped
  to ``/api/v1/auth``; JavaScript can never read it.
* ``/auth/refresh`` is the one cookie-authenticated call, so it also requires the
  ``X-CSRF-Token`` header carrying the CSRF token returned with the previous token pair
  (bound server-side to that refresh token).
"""

import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, Depends, Header, Request, Response, status
from pydantic import BaseModel, Field

from app.api.deps import (
    authenticated,
    client_ip,
    get_auth_service,
    rate_limited,
)
from app.application.auth.errors import InvalidToken
from app.application.auth.service import AuthService, IssuedSession, StudentRegistration
from app.domain.auth.policies import Principal

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "__Secure-mm_refresh"
COOKIE_PATH = "/api/v1/auth"


class RegisterIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)
    full_name: str = Field(min_length=1, max_length=200)
    department_code: str = Field(min_length=1, max_length=20)
    student_number: str = Field(min_length=1, max_length=40)
    enrollment_year: int = Field(ge=1990, le=2100)
    year_of_study: int = Field(ge=1, le=8)
    accept_terms: Literal[True]


class LoginIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)
    # Only needed when the same e-mail exists in more than one institution.
    institution: str | None = Field(default=None, max_length=80)


class TokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class ForgotIn(BaseModel):
    email: str = Field(max_length=320)
    institution: str | None = Field(default=None, max_length=80)


class ResetIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    new_password: str = Field(max_length=1024)


class UserRef(BaseModel):
    id: str
    role: str
    institution_id: str


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - not a secret
    expires_in: int
    csrf_token: str
    user: UserRef


class Accepted(BaseModel):
    status: str


def _token_response(response: Response, issued: IssuedSession) -> TokenOut:
    now = dt.datetime.now(dt.UTC)
    response.set_cookie(
        REFRESH_COOKIE,
        issued.refresh_token,
        max_age=max(1, int((issued.refresh_expires_at - now).total_seconds())),
        path=COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite="strict",
    )
    return TokenOut(
        access_token=issued.access_token,
        expires_in=max(1, int((issued.access_expires_at - now).total_seconds())),
        csrf_token=issued.csrf_token,
        user=UserRef(
            id=str(issued.user_id),
            role=issued.role.value,
            institution_id=str(issued.institution_id),
        ),
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        REFRESH_COOKIE, path=COOKIE_PATH, secure=True, httponly=True, samesite="strict"
    )


Auth = Annotated[AuthService, Depends(get_auth_service)]


@router.post(
    "/register",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limited("auth"))],
)
async def register(body: RegisterIn, request: Request, auth: Auth) -> Accepted:
    """PUBLIC. Student self-registration with an institutional e-mail; sends a verification
    link. The response is identical whether or not the e-mail was already registered."""
    await auth.register_student(
        StudentRegistration(
            email=body.email,
            password=body.password,
            full_name=body.full_name,
            department_code=body.department_code,
            student_number=body.student_number,
            enrollment_year=body.enrollment_year,
            year_of_study=body.year_of_study,
        ),
        client_ip=client_ip(request),
    )
    return Accepted(status="verification_sent")


@router.post("/verify-email", dependencies=[Depends(rate_limited("auth"))])
async def verify_email(body: TokenIn, auth: Auth) -> Accepted:
    """PUBLIC (one-time token)."""
    await auth.verify_email(body.token)
    return Accepted(status="verified")


@router.post("/login", dependencies=[Depends(rate_limited("auth"))])
async def login(body: LoginIn, request: Request, response: Response, auth: Auth) -> TokenOut:
    """PUBLIC. Same 401 for unknown e-mail, wrong password, locked or inactive account."""
    issued = await auth.login(
        body.email, body.password, institution_slug=body.institution, client_ip=client_ip(request)
    )
    return _token_response(response, issued)


@router.post("/refresh", dependencies=[Depends(rate_limited("auth"))])
async def refresh(
    request: Request,
    response: Response,
    auth: Auth,
    refresh_cookie: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
    csrf: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> TokenOut:
    """PUBLIC (refresh cookie + CSRF header). Rotates the refresh token."""
    if not refresh_cookie:
        raise InvalidToken
    issued = await auth.refresh(refresh_cookie, csrf, client_ip=client_ip(request))
    return _token_response(response, issued)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    auth: Auth,
    principal: Annotated[Principal, Depends(authenticated())],
) -> Response:
    """Any signed-in user. Revokes this session (its access and refresh tokens)."""
    await auth.logout(principal.session_id, principal.user_id)
    response.status_code = status.HTTP_204_NO_CONTENT
    _clear_refresh_cookie(response)
    return response


@router.post(
    "/password/forgot",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limited("auth"))],
)
async def forgot_password(body: ForgotIn, auth: Auth) -> Accepted:
    """PUBLIC. Always 202, whether or not the account exists."""
    await auth.request_password_reset(body.email, institution_slug=body.institution)
    return Accepted(status="if_the_account_exists_a_link_was_sent")


@router.post("/password/reset", dependencies=[Depends(rate_limited("auth"))])
async def reset_password(body: ResetIn, auth: Auth) -> Accepted:
    """PUBLIC (one-time token). Also completes first-time account setup. Signs out
    every existing session of the account."""
    await auth.reset_password(body.token, body.new_password)
    return Accepted(status="password_updated")
