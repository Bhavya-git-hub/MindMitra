"""Authentication flows through the real API and a real PostgreSQL database."""

import base64
import datetime as dt
import json
import uuid

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.api.deps import AppState
from app.api.main import create_app
from app.api.rate_limit import SlidingWindowRateLimiter
from app.application.auth.delivery import InMemoryTokenOutbox
from app.core.access_tokens import AccessTokenCodec, generate_private_key_pem, load_private_key
from app.core.config import get_settings
from app.infrastructure.db import models as m
from app.infrastructure.db.enums import (
    AuditOutcome,
    OneTimeTokenPurpose,
    SessionRevokeReason,
    UserRole,
    UserStatus,
)
from app.infrastructure.db.session import create_session_factory
from tests.api_helpers import API, call, login, token_for
from tests.api_world import Actor, Builder, World

pytestmark = pytest.mark.asyncio

REFRESH_COOKIE = "__Secure-mm_refresh"
NEW_PASSWORD = "Another-synthetic-passphrase-42"


async def _fresh(api_db: AsyncSession, world: World, role: UserRole = UserRole.STUDENT) -> Actor:
    """A brand-new active user, for tests that end sessions or change credentials."""
    b = Builder(api_db, world.password)
    dept = world.dept_a if role in (UserRole.STUDENT, UserRole.TEACHER) else None
    actor = await b.user(world.inst_a, role, department_id=dept)
    await api_db.commit()
    return actor


def _state(app: FastAPI) -> AppState:
    state: AppState = app.state.mm
    return state


async def _refresh(
    client: httpx.AsyncClient, csrf: str | None, *, cookie: str | None = None
) -> httpx.Response:
    """Call /auth/refresh with the client's cookie jar, or with exactly ``cookie``."""
    headers = {"X-CSRF-Token": csrf} if csrf is not None else {}
    if cookie is not None:
        client.cookies.clear()
        headers["Cookie"] = f"{REFRESH_COOKIE}={cookie}"
    return await client.post(f"{API}/auth/refresh", headers=headers)


# ---- login -----------------------------------------------------------------------------------


async def test_login_issues_tokens_and_a_locked_down_refresh_cookie(
    client: httpx.AsyncClient, world: World
) -> None:
    r = await login(client, world.student.email, world.password)
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert 0 < body["expires_in"] <= 600
    assert body["user"] == {
        "id": str(world.student.user_id),
        "role": "student",
        "institution_id": str(world.inst_a),
    }
    assert body["csrf_token"] and body["access_token"].count(".") == 2
    assert REFRESH_COOKIE not in body and "refresh_token" not in body

    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{REFRESH_COOKIE}=")
    lowered = cookie.lower()
    for attr in ("httponly", "secure", "samesite=strict", "path=/api/v1/auth"):
        assert attr in lowered, cookie

    me = await call(client, "GET", "/me", token=body["access_token"])
    assert me.status_code == 200
    assert me.json()["role"] == "student"
    assert "ai_conversation:read:own" in me.json()["permissions"]


async def test_login_failures_are_indistinguishable(
    client: httpx.AsyncClient, world: World, api_db: AsyncSession
) -> None:
    invited = await Builder(api_db, world.password).user(
        world.inst_a, UserRole.STUDENT, department_id=world.dept_a, status=UserStatus.INVITED
    )
    await api_db.commit()
    attempts = [
        (f"nobody-{uuid.uuid4().hex[:6]}@test.example", world.password),  # unknown account
        (world.other_student.email, "wrong-password-123"),  # wrong password
        (invited.email, world.password),  # right password, account not active
    ]
    bodies = []
    for email, password in attempts:
        r = await login(client, email, password)
        assert r.status_code == 401
        body = r.json()
        body.pop("request_id")
        bodies.append(body)
    assert bodies[0] == bodies[1] == bodies[2]
    assert bodies[0]["detail"] == "Invalid email or password."


async def test_repeated_failures_lock_the_account_temporarily(
    client: httpx.AsyncClient, world: World, api_db: AsyncSession
) -> None:
    actor = await _fresh(api_db, world)
    threshold = get_settings().login_lockout_threshold
    for _ in range(threshold):
        assert (await login(client, actor.email, "wrong-password-123")).status_code == 401
    # Now even the right password is refused, with the same answer.
    r = await login(client, actor.email, world.password)
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid email or password."
    cred = await api_db.get(m.Credential, actor.user_id, populate_existing=True)
    assert cred is not None and cred.locked_until is not None
    assert cred.locked_until <= dt.datetime.now(dt.UTC) + dt.timedelta(minutes=15)

    # Once the lock expires, the right password works and the counter resets.
    await api_db.execute(
        update(m.Credential)
        .where(m.Credential.user_id == actor.user_id)
        .values(locked_until=dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1))
    )
    await api_db.commit()
    assert (await login(client, actor.email, world.password)).status_code == 200
    cred = await api_db.get(m.Credential, actor.user_id, populate_existing=True)
    assert cred is not None and cred.failed_attempts == 0 and cred.locked_until is None


async def test_passwords_are_stored_as_argon2id(api_db: AsyncSession, world: World) -> None:
    hashes = list(await api_db.scalars(select(m.Credential.password_hash).limit(50)))
    assert hashes and all(h.startswith("$argon2id$") for h in hashes)
    assert all(world.password not in h for h in hashes)


async def test_login_is_audited_without_secrets(
    client: httpx.AsyncClient, world: World, api_db: AsyncSession
) -> None:
    actor = await _fresh(api_db, world)
    await login(client, actor.email, "wrong-password-123")
    await login(client, actor.email, world.password)
    rows = (
        await api_db.execute(
            select(m.AuditLog.outcome, m.AuditLog.reason, m.AuditLog.details, m.AuditLog.ip_hash)
            .where(m.AuditLog.actor_id == actor.user_id, m.AuditLog.action == "auth.login")
            .order_by(m.AuditLog.seq)
        )
    ).all()
    assert [(r.outcome, r.reason) for r in rows] == [
        (AuditOutcome.DENIED, "bad_password"),
        (AuditOutcome.ALLOWED, None),
    ]
    for r in rows:
        assert world.password not in json.dumps(r.details)
        assert r.ip_hash is not None and "203.0.113.10" not in r.ip_hash


# ---- access tokens ---------------------------------------------------------------------------


def _b64(data: dict[str, object]) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


async def test_forged_and_malformed_access_tokens_are_rejected(
    client: httpx.AsyncClient, world: World, api_app: FastAPI
) -> None:
    good = await token_for(client, world.student, world.password)
    codec = _state(api_app).codec
    claims = codec.decode(good)
    settings = get_settings()
    now = dt.datetime.now(dt.UTC)

    def forge(c: AccessTokenCodec, *, role: str = "student", at: dt.datetime = now) -> str:
        return c.issue(
            user_id=claims.user_id,
            institution_id=claims.institution_id,
            role=role,
            session_id=claims.session_id,
            now=at,
        )[0]

    other_key = AccessTokenCodec(
        load_private_key(generate_private_key_pem()),
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        ttl=dt.timedelta(minutes=10),
    )
    wrong_aud = AccessTokenCodec(
        load_private_key(settings.jwt_private_key.get_secret_value()),
        issuer=settings.jwt_issuer,
        audience="someone-else",
        ttl=dt.timedelta(minutes=10),
    )
    header, payload, sig = good.split(".")
    decoded = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    escalated = dict(decoded, role="administrator")

    bad_tokens = {
        "garbage": "not-a-jwt",
        "signed by another key": forge(other_key),
        "wrong audience": forge(wrong_aud),
        "expired": forge(codec, at=now - dt.timedelta(hours=1)),
        "alg none": f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{payload}.",
        "alg HS256": f"{_b64({'alg': 'HS256', 'typ': 'JWT'})}.{payload}.{sig}",
        "payload edited (role escalation)": f"{header}.{_b64(escalated)}.{sig}",
    }
    for label, token in bad_tokens.items():
        r = await call(client, "GET", "/me", token=token)
        assert r.status_code == 401, label

    # A validly signed token whose role claim does not match the account is also refused.
    mismatched = forge(codec, role="administrator")
    assert (await call(client, "GET", "/admin/users", token=mismatched)).status_code == 401
    assert (await call(client, "GET", "/me", token=good)).status_code == 200


async def test_access_token_stops_working_when_account_is_disabled(
    client: httpx.AsyncClient, world: World, api_db: AsyncSession
) -> None:
    actor = await _fresh(api_db, world)
    tok = (await login(client, actor.email, world.password)).json()["access_token"]
    assert (await call(client, "GET", "/me", token=tok)).status_code == 200

    admin_tok = await token_for(client, world.admin, world.password)
    r = await call(
        client,
        "PATCH",
        f"/admin/users/{actor.user_id}",
        token=admin_tok,
        json={"status": "suspended"},
    )
    assert r.status_code == 200 and r.json()["status"] == "suspended"
    assert (await call(client, "GET", "/me", token=tok)).status_code == 401
    assert (await login(client, actor.email, world.password)).status_code == 401
    reason = await api_db.scalar(
        select(m.AuthSession.revoked_reason).where(m.AuthSession.user_id == actor.user_id)
    )
    assert reason is SessionRevokeReason.ACCOUNT_DISABLED

    r = await call(
        client,
        "PATCH",
        f"/admin/users/{actor.user_id}",
        token=admin_tok,
        json={"status": "active"},
    )
    assert r.status_code == 200
    assert (await login(client, actor.email, world.password)).status_code == 200


@pytest.mark.parametrize("status", [UserStatus.SUSPENDED, UserStatus.DEACTIVATED])
async def test_access_token_checks_account_status_on_every_request(
    client: httpx.AsyncClient, world: World, api_db: AsyncSession, status: UserStatus
) -> None:
    """Even if a status change somehow skipped session revocation, the token stops working."""
    actor = await _fresh(api_db, world)
    tok = (await login(client, actor.email, world.password)).json()["access_token"]
    await api_db.execute(update(m.User).where(m.User.id == actor.user_id).values(status=status))
    await api_db.commit()
    assert (await call(client, "GET", "/me", token=tok)).status_code == 401


async def test_access_token_stops_working_when_account_is_deleted(
    client: httpx.AsyncClient, world: World, api_db: AsyncSession
) -> None:
    actor = await _fresh(api_db, world)
    tok = (await login(client, actor.email, world.password)).json()["access_token"]
    await api_db.execute(
        update(m.User).where(m.User.id == actor.user_id).values(deleted_at=dt.datetime.now(dt.UTC))
    )
    await api_db.commit()
    assert (await call(client, "GET", "/me", token=tok)).status_code == 401


async def test_access_token_stops_working_when_role_changes(
    client: httpx.AsyncClient, world: World, api_db: AsyncSession
) -> None:
    actor = await _fresh(api_db, world, UserRole.TEACHER)
    tok = (await login(client, actor.email, world.password)).json()["access_token"]
    assert (await call(client, "GET", "/insights/mood-summary", token=tok)).status_code == 200
    # An admin re-roles the account (profile swapped in the same transaction).
    await api_db.execute(delete(m.Teacher).where(m.Teacher.user_id == actor.user_id))
    await api_db.execute(
        update(m.User).where(m.User.id == actor.user_id).values(role=UserRole.THERAPIST)
    )
    api_db.add(
        m.Therapist(
            user_id=actor.user_id,
            institution_id=world.inst_a,
            licence_number=f"L-{uuid.uuid4().hex[:8]}",
        )
    )
    await api_db.commit()
    assert (await call(client, "GET", "/me", token=tok)).status_code == 401


# ---- refresh tokens --------------------------------------------------------------------------


async def test_refresh_rotates_and_detects_reuse(
    client: httpx.AsyncClient, world: World, api_db: AsyncSession
) -> None:
    actor = await _fresh(api_db, world)
    first = await login(client, actor.email, world.password)
    old_cookie = first.cookies[REFRESH_COOKIE]
    old_csrf = first.json()["csrf_token"]

    second = await _refresh(client, old_csrf)
    assert second.status_code == 200, second.text
    new_cookie = second.cookies[REFRESH_COOKIE]
    assert new_cookie != old_cookie
    new_access = second.json()["access_token"]
    assert (await call(client, "GET", "/me", token=new_access)).status_code == 200

    # Replaying the rotated-out token (as a thief would) kills the whole session.
    assert (await _refresh(client, old_csrf, cookie=old_cookie)).status_code == 401
    assert (await call(client, "GET", "/me", token=new_access)).status_code == 401
    r = await _refresh(client, second.json()["csrf_token"], cookie=new_cookie)
    assert r.status_code == 401
    reason = await api_db.scalar(
        select(m.AuthSession.revoked_reason).where(m.AuthSession.user_id == actor.user_id)
    )
    assert reason is SessionRevokeReason.REFRESH_REUSE


async def test_refresh_requires_the_matching_csrf_token(
    client: httpx.AsyncClient, world: World, api_db: AsyncSession
) -> None:
    actor = await _fresh(api_db, world)
    first = await login(client, actor.email, world.password)
    csrf = first.json()["csrf_token"]
    assert (await _refresh(client, None)).status_code == 403
    assert (await _refresh(client, "x" * 43)).status_code == 403
    # A failed CSRF check neither consumes the token nor revokes the session.
    assert (await _refresh(client, csrf)).status_code == 200


async def test_refresh_without_cookie_is_rejected(client: httpx.AsyncClient) -> None:
    assert (await _refresh(client, "anything")).status_code == 401


async def test_refresh_token_never_outlives_the_session(
    client: httpx.AsyncClient, world: World, api_db: AsyncSession
) -> None:
    actor = await _fresh(api_db, world, UserRole.THERAPIST)
    await login(client, actor.email, world.password)
    sess = await api_db.scalar(select(m.AuthSession).where(m.AuthSession.user_id == actor.user_id))
    assert sess is not None
    lifetime = sess.absolute_expires_at - sess.created_at
    assert lifetime <= dt.timedelta(seconds=get_settings().staff_session_max_seconds + 5)
    tokens = list(
        await api_db.scalars(select(m.RefreshToken).where(m.RefreshToken.session_id == sess.id))
    )
    assert tokens and all(t.expires_at <= sess.absolute_expires_at for t in tokens)
    assert all(len(t.token_hash) == 64 for t in tokens)  # stored hashed, never raw


# ---- logout ----------------------------------------------------------------------------------


async def test_logout_revokes_access_and_refresh(
    client: httpx.AsyncClient, world: World, api_db: AsyncSession
) -> None:
    actor = await _fresh(api_db, world)
    first = await login(client, actor.email, world.password)
    tok, csrf = first.json()["access_token"], first.json()["csrf_token"]
    r = await call(client, "POST", "/auth/logout", token=tok)
    assert r.status_code == 204
    assert REFRESH_COOKIE in r.headers.get("set-cookie", "")  # cleared
    assert (await call(client, "GET", "/me", token=tok)).status_code == 401
    assert (await _refresh(client, csrf, cookie=first.cookies[REFRESH_COOKIE])).status_code == 401


# ---- registration and e-mail verification ----------------------------------------------------


def _registration(email: str, password: str, number: str) -> dict[str, object]:
    return {
        "email": email,
        "password": password,
        "full_name": "Synthetic Registrant",
        "department_code": "CS",
        "student_number": number,
        "enrollment_year": 2025,
        "year_of_study": 2,
        "accept_terms": True,
    }


async def test_register_verify_then_login(
    client: httpx.AsyncClient, world: World, outbox: InMemoryTokenOutbox, api_db: AsyncSession
) -> None:
    email = f"new.{uuid.uuid4().hex[:8]}@students.synthetic.example"
    number = f"R-{uuid.uuid4().hex[:8]}"
    r = await call(
        client, "POST", "/auth/register", json=_registration(email, NEW_PASSWORD, number)
    )
    assert r.status_code == 202
    assert (await login(client, email, NEW_PASSWORD)).status_code == 401  # not verified yet

    token = outbox.latest(email, OneTimeTokenPurpose.EMAIL_VERIFICATION)
    assert token is not None
    assert (
        await call(client, "POST", "/auth/verify-email", json={"token": token})
    ).status_code == 200
    assert (
        await call(client, "POST", "/auth/verify-email", json={"token": token})
    ).status_code == 401

    r = await login(client, email, NEW_PASSWORD)
    assert r.status_code == 200 and r.json()["user"]["role"] == "student"
    consent = await api_db.scalar(
        select(m.Consent.scope).where(m.Consent.user_id == uuid.UUID(r.json()["user"]["id"]))
    )
    assert consent is not None

    # Registering again with the same e-mail looks identical and sends nothing new.
    sent = len(outbox.sent)
    again = await call(
        client, "POST", "/auth/register", json=_registration(email, NEW_PASSWORD, "R-other")
    )
    assert again.status_code == 202 and again.json() == {"status": "verification_sent"}
    assert len(outbox.sent) == sent


async def test_registration_only_with_a_strong_password_and_known_domain(
    client: httpx.AsyncClient,
) -> None:
    n = uuid.uuid4().hex[:8]
    weak = await call(
        client,
        "POST",
        "/auth/register",
        json=_registration(f"weak.{n}@students.synthetic.example", "password1234", f"W-{n}"),
    )
    assert weak.status_code == 422
    assert weak.json()["errors"][0]["loc"] == ["body", "password"]
    assert "password1234" not in weak.text  # input is never echoed

    foreign = await call(
        client,
        "POST",
        "/auth/register",
        json=_registration(f"x.{n}@gmail.com", NEW_PASSWORD, f"F-{n}"),
    )
    assert foreign.status_code == 422

    no_terms = _registration(f"t.{n}@students.synthetic.example", NEW_PASSWORD, f"T-{n}")
    no_terms["accept_terms"] = False
    assert (await call(client, "POST", "/auth/register", json=no_terms)).status_code == 422


async def test_registration_cannot_choose_a_role(
    client: httpx.AsyncClient, api_db: AsyncSession
) -> None:
    n = uuid.uuid4().hex[:8]
    email = f"sneaky.{n}@staff.synthetic.example"
    body = _registration(email, NEW_PASSWORD, f"S-{n}") | {"role": "administrator"}
    r = await call(client, "POST", "/auth/register", json=body)
    assert r.status_code == 202  # the extra field is ignored
    role = await api_db.scalar(select(m.User.role).where(m.User.email == email))
    assert role is UserRole.STUDENT


# ---- password reset --------------------------------------------------------------------------


async def test_password_reset_flow_signs_out_everywhere(
    client: httpx.AsyncClient, world: World, outbox: InMemoryTokenOutbox, api_db: AsyncSession
) -> None:
    actor = await _fresh(api_db, world)
    old_tok = (await login(client, actor.email, world.password)).json()["access_token"]

    r = await call(client, "POST", "/auth/password/forgot", json={"email": actor.email})
    assert r.status_code == 202
    token = outbox.latest(actor.email, OneTimeTokenPurpose.PASSWORD_RESET)
    assert token is not None

    weak = await call(
        client, "POST", "/auth/password/reset", json={"token": token, "new_password": "short"}
    )
    assert weak.status_code == 422
    ok = await call(
        client, "POST", "/auth/password/reset", json={"token": token, "new_password": NEW_PASSWORD}
    )
    assert ok.status_code == 200  # the weak attempt did not burn the token
    again = await call(
        client, "POST", "/auth/password/reset", json={"token": token, "new_password": NEW_PASSWORD}
    )
    assert again.status_code == 401

    assert (await call(client, "GET", "/me", token=old_tok)).status_code == 401
    assert (await login(client, actor.email, world.password)).status_code == 401
    assert (await login(client, actor.email, NEW_PASSWORD)).status_code == 200


async def test_forgot_password_does_not_reveal_accounts(
    client: httpx.AsyncClient, outbox: InMemoryTokenOutbox
) -> None:
    sent = len(outbox.sent)
    email = f"ghost.{uuid.uuid4().hex[:8]}@test.example"
    r = await call(client, "POST", "/auth/password/forgot", json={"email": email})
    assert r.status_code == 202
    assert r.json() == {"status": "if_the_account_exists_a_link_was_sent"}
    assert len(outbox.sent) == sent


async def test_reset_token_cannot_be_forged(client: httpx.AsyncClient) -> None:
    r = await call(
        client,
        "POST",
        "/auth/password/reset",
        json={"token": "A" * 43, "new_password": NEW_PASSWORD},
    )
    assert r.status_code == 401


# ---- admin-created accounts ------------------------------------------------------------------


async def test_admin_creates_user_who_sets_own_password(
    client: httpx.AsyncClient, world: World, outbox: InMemoryTokenOutbox
) -> None:
    admin_tok = await token_for(client, world.admin, world.password)
    email = f"new.therapist.{uuid.uuid4().hex[:6]}@care.synthetic.example"
    r = await call(
        client,
        "POST",
        "/admin/users",
        token=admin_tok,
        json={
            "email": email,
            "full_name": "New Synthetic Therapist",
            "role": "therapist",
            "licence_number": f"L-{uuid.uuid4().hex[:8]}",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "invited" and r.json()["role"] == "therapist"
    assert "password" not in r.text

    dup = await call(
        client,
        "POST",
        "/admin/users",
        token=admin_tok,
        json={"email": email, "full_name": "Dup", "role": "therapist", "licence_number": "L-dup"},
    )
    assert dup.status_code == 409

    token = outbox.latest(email, OneTimeTokenPurpose.ACCOUNT_SETUP)
    assert token is not None
    r = await call(
        client, "POST", "/auth/password/reset", json={"token": token, "new_password": NEW_PASSWORD}
    )
    assert r.status_code == 200
    r = await login(client, email, NEW_PASSWORD)
    assert r.status_code == 200 and r.json()["user"]["role"] == "therapist"
    assert r.json()["user"]["institution_id"] == str(world.inst_a)


async def test_non_admins_cannot_create_users(client: httpx.AsyncClient, world: World) -> None:
    for actor in (world.student, world.therapist, world.teacher):
        tok = await token_for(client, actor, world.password)
        r = await call(
            client,
            "POST",
            "/admin/users",
            token=tok,
            json={"email": "evil@test.example", "full_name": "Evil", "role": "administrator"},
        )
        assert r.status_code == 403


# ---- transport hardening ---------------------------------------------------------------------


async def test_public_auth_endpoints_are_rate_limited(api_engine: AsyncEngine) -> None:
    app = create_app(
        get_settings(),
        session_factory=create_session_factory(api_engine),
        delivery=InMemoryTokenOutbox(),
        limiter=SlidingWindowRateLimiter(3),
    )
    transport = httpx.ASGITransport(app=app, client=("198.51.100.7", 1))
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as c:
        codes = [
            (
                await c.post(f"{API}/auth/password/forgot", json={"email": "a@test.example"})
            ).status_code
            for _ in range(4)
        ]
        assert codes == [202, 202, 202, 429]
        last = await c.post(f"{API}/auth/login", json={"email": "a@test.example", "password": "x"})
        assert last.status_code == 429 and int(last.headers["retry-after"]) >= 1


async def test_security_headers_and_request_id(client: httpx.AsyncClient) -> None:
    r = await client.get(f"{API}/health/live", headers={"X-Request-ID": "abc12345-req"})
    assert r.status_code == 200
    assert r.headers["x-request-id"] == "abc12345-req"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    bad = await client.get(f"{API}/health/live", headers={"X-Request-ID": "<script>"})
    assert bad.headers["x-request-id"] != "<script>"


async def test_app_refuses_to_start_without_a_real_sender_in_production(
    api_engine: AsyncEngine,
) -> None:
    settings = get_settings().model_copy(update={"app_env": "production"})
    with pytest.raises(RuntimeError, match="sender"):
        create_app(settings, session_factory=create_session_factory(api_engine))
