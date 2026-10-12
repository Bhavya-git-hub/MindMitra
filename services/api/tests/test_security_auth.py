"""Regression tests from the authentication / session / configuration security review.

Each test proves a property against the real app and PostgreSQL: secrets never appear in
configuration errors, a 500 keeps the security headers, registration costs the same whether
or not the e-mail is known, a password change kills every other reset link, another
institution cannot block someone's password reset, and the auth rate limit cannot be dodged
with forwarding headers.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.api.main import create_app
from app.api.rate_limit import SlidingWindowRateLimiter
from app.application.auth.delivery import InMemoryTokenOutbox
from app.core.access_tokens import generate_private_key_pem
from app.core.config import Settings, get_settings
from app.core.crypto import generate_key
from app.core.security import hash_password
from app.infrastructure.db.enums import OneTimeTokenPurpose, UserRole
from app.infrastructure.db.session import create_session_factory
from tests.api_helpers import API, call, login, token_for
from tests.api_world import Builder, World

pytestmark = pytest.mark.asyncio

NEW_PASSWORD = "Another-synthetic-passphrase-42"
SECRET = "SUPERSECRET-must-not-be-echoed"  # noqa: S105 - a marker, not a credential
WEB_ORIGIN = "https://app.synthetic.example"


# ---- configuration errors never echo secret values ---------------------------------------


def _settings_values(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "app_env": "production",
        "database_url": f"postgresql+asyncpg://mm:{SECRET}@db.internal:5432/mm?ssl=require",
        "field_encryption_key": generate_key(),
        "jwt_private_key": generate_private_key_pem(),
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"database_url": f"postgresql://mm:{SECRET}@db/mm"}, id="wrong-driver"),
        pytest.param(
            {"database_url": f"postgresql+asyncpg://mm:{SECRET}@db/mm"}, id="no-tls-in-production"
        ),
        pytest.param({"field_encryption_key": SECRET}, id="bad-encryption-key"),
        pytest.param({"jwt_private_key": f"-----BEGIN {SECRET}"}, id="bad-jwt-key"),
        pytest.param(
            {"ml_service_url": "https://ml.internal", "ml_service_token": SECRET[:20]},
            id="short-ml-token",
        ),
        pytest.param(
            {"ml_service_url": "http://ml.internal", "ml_service_token": SECRET * 2},
            id="ml-without-https",
        ),
    ],
)
async def test_settings_errors_never_echo_secret_values(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, **_settings_values(**overrides))  # type: ignore[call-arg]
    # str() is what a crashing process prints into the deployment logs.
    text = str(caught.value)
    assert "SUPERSECRET" not in text and SECRET[:20] not in text


# ---- unhandled errors ------------------------------------------------------------------------


@pytest_asyncio.fixture
async def boom_client(api_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    settings = get_settings().model_copy(update={"cors_origins": WEB_ORIGIN})
    app = create_app(
        settings, session_factory=create_session_factory(api_engine), delivery=InMemoryTokenOutbox()
    )

    async def boom() -> None:
        raise RuntimeError(f"internal detail {SECRET}")

    app.add_api_route(f"{API}/boom-for-test", boom)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as c:
        yield c


async def test_unhandled_errors_keep_security_headers_and_request_id(
    boom_client: httpx.AsyncClient,
) -> None:
    r = await boom_client.get(
        f"{API}/boom-for-test", headers={"X-Request-ID": "req-500-check", "Origin": WEB_ORIGIN}
    )
    assert r.status_code == 500
    assert r.headers["content-type"] == "application/problem+json"
    assert SECRET not in r.text and "RuntimeError" not in r.text
    assert r.json()["request_id"] == "req-500-check"
    assert r.headers["x-request-id"] == "req-500-check"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert "max-age=" in r.headers["strict-transport-security"]
    # The web app can read the problem (and its request id) cross-origin.
    assert r.headers["access-control-allow-origin"] == WEB_ORIGIN


# ---- CORS ------------------------------------------------------------------------------------


async def test_cors_allows_only_configured_origins(boom_client: httpx.AsyncClient) -> None:
    ok = await boom_client.get(f"{API}/health/live", headers={"Origin": WEB_ORIGIN})
    assert ok.headers["access-control-allow-origin"] == WEB_ORIGIN
    assert ok.headers["access-control-allow-credentials"] == "true"

    for origin in ("https://evil.example", "null", "https://app.synthetic.example.evil.example"):
        r = await boom_client.get(f"{API}/health/live", headers={"Origin": origin})
        assert "access-control-allow-origin" not in r.headers, origin
        pre = await boom_client.options(
            f"{API}/auth/refresh",
            headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
        )
        assert "access-control-allow-origin" not in pre.headers, origin


# ---- registration does not reveal known e-mails by its cost ---------------------------------


def _registration(email: str, number: str) -> dict[str, object]:
    return {
        "email": email,
        "password": NEW_PASSWORD,
        "full_name": "Synthetic Student",
        "department_code": "PSY",
        "student_number": number,
        "enrollment_year": 2024,
        "year_of_study": 2,
        "accept_terms": True,
    }


async def test_registering_a_known_email_costs_the_same_password_hashing(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    def counting(password: str) -> str:
        calls.append(1)
        return hash_password(password)

    monkeypatch.setattr("app.application.auth.service.hash_password", counting)
    email = f"known.{uuid.uuid4().hex[:8]}@students.synthetic.example"

    first = await call(
        client, "POST", "/auth/register", json=_registration(email, f"K-{uuid.uuid4().hex[:8]}")
    )
    assert first.status_code == 202
    new_account_hashes = len(calls)
    assert new_account_hashes >= 1

    calls.clear()
    again = await call(
        client, "POST", "/auth/register", json=_registration(email, f"K-{uuid.uuid4().hex[:8]}")
    )
    assert again.status_code == 202 and again.json() == first.json()
    # Before the fix a known e-mail returned before any Argon2 work (~6 ms against ~150 ms).
    assert len(calls) == new_account_hashes


# ---- one-time links ------------------------------------------------------------------------


async def test_password_change_invalidates_every_other_reset_or_setup_link(
    client: httpx.AsyncClient, world: World, outbox: InMemoryTokenOutbox
) -> None:
    admin = await token_for(client, world.admin, world.password)
    email = f"links.{uuid.uuid4().hex[:8]}@care.synthetic.example"
    created = await call(
        client,
        "POST",
        "/admin/users",
        token=admin,
        json={
            "email": email,
            "full_name": "Synthetic Therapist",
            "role": "therapist",
            "licence_number": f"L-{uuid.uuid4().hex[:8]}",
        },
    )
    assert created.status_code == 201
    setup = outbox.latest(email, OneTimeTokenPurpose.ACCOUNT_SETUP)
    assert setup is not None

    # The administrator activates the account before the set-up link is used; the person then
    # chooses a password through "forgot password".
    activated = await call(
        client,
        "PATCH",
        f"/admin/users/{created.json()['id']}",
        token=admin,
        json={"status": "active"},
    )
    assert activated.status_code == 200
    assert (
        await call(client, "POST", "/auth/password/forgot", json={"email": email})
    ).status_code == 202
    reset = outbox.latest(email, OneTimeTokenPurpose.PASSWORD_RESET)
    assert reset is not None
    done = await call(
        client, "POST", "/auth/password/reset", json={"token": reset, "new_password": NEW_PASSWORD}
    )
    assert done.status_code == 200

    # The older set-up link must not be able to overwrite the password just chosen.
    stale = await call(
        client,
        "POST",
        "/auth/password/reset",
        json={"token": setup, "new_password": NEW_PASSWORD + "-taken-over"},
    )
    assert stale.status_code == 401
    assert (await login(client, email, NEW_PASSWORD)).status_code == 200


async def test_another_institution_cannot_block_a_password_reset(
    client: httpx.AsyncClient, world: World, outbox: InMemoryTokenOutbox, api_db: AsyncSession
) -> None:
    victim = await Builder(api_db, world.password).user(
        world.inst_a, UserRole.STUDENT, department_id=world.dept_a
    )
    await api_db.commit()

    # An administrator of institution B creates (and activates) an account with the same address.
    b_admin = await token_for(client, world.b_admin, world.password)
    dup = await call(
        client,
        "POST",
        "/admin/users",
        token=b_admin,
        json={
            "email": victim.email,
            "full_name": "Duplicate",
            "role": "therapist",
            "licence_number": f"L-{uuid.uuid4().hex[:8]}",
        },
    )
    assert dup.status_code == 201
    assert (
        await call(
            client,
            "PATCH",
            f"/admin/users/{dup.json()['id']}",
            token=b_admin,
            json={"status": "active"},
        )
    ).status_code == 200

    sent = len(outbox.sent)
    r = await call(client, "POST", "/auth/password/forgot", json={"email": victim.email})
    assert r.status_code == 202
    own = [
        d.token
        for d in outbox.sent[sent:]
        if d.user_id == victim.user_id and d.purpose is OneTimeTokenPurpose.PASSWORD_RESET
    ]
    assert len(own) == 1, "the real owner must still receive a reset link"
    ok = await call(
        client, "POST", "/auth/password/reset", json={"token": own[0], "new_password": NEW_PASSWORD}
    )
    assert ok.status_code == 200
    # The duplicate never set a password, so the address is not ambiguous for login.
    signed_in = await login(client, victim.email, NEW_PASSWORD)
    assert signed_in.status_code == 200
    assert signed_in.json()["user"]["id"] == str(victim.user_id)


# ---- registering someone else's address cannot take their account -------------------------

ATTACKER_PASSWORD = "Attacker-chosen-passphrase-77"  # noqa: S105 - synthetic


def _sign_up(email: str, password: str, number: str) -> dict[str, object]:
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


async def test_a_link_sent_because_a_stranger_registered_cannot_activate_their_password(
    client: httpx.AsyncClient, outbox: InMemoryTokenOutbox
) -> None:
    """The stranger registers a student's address; the student clicks the link that arrives.
    Without the stranger's password the link does nothing, so the stranger never gets in."""
    email = f"victim.{uuid.uuid4().hex[:8]}@students.synthetic.example"
    r = await call(client, "POST", "/auth/register", json=_sign_up(email, ATTACKER_PASSWORD, "A-1"))
    assert r.status_code == 202
    link = outbox.latest(email, OneTimeTokenPurpose.EMAIL_VERIFICATION)
    assert link is not None
    clicked = await call(
        client, "POST", "/auth/verify-email", json={"token": link, "password": NEW_PASSWORD}
    )
    assert clicked.status_code == 401
    assert (await login(client, email, ATTACKER_PASSWORD)).status_code == 401


async def test_the_real_student_registering_later_gets_their_own_link_and_password(
    client: httpx.AsyncClient, outbox: InMemoryTokenOutbox
) -> None:
    """A stranger registered the address first. The student's own registration used to send
    nothing, leaving only the stranger's link (which activated the stranger's password)."""
    email = f"victim.{uuid.uuid4().hex[:8]}@students.synthetic.example"
    number = f"V-{uuid.uuid4().hex[:8]}"
    await call(client, "POST", "/auth/register", json=_sign_up(email, ATTACKER_PASSWORD, number))
    stranger_link = outbox.latest(email, OneTimeTokenPurpose.EMAIL_VERIFICATION)

    again = await call(client, "POST", "/auth/register", json=_sign_up(email, NEW_PASSWORD, number))
    assert again.status_code == 202 and again.json() == {"status": "verification_sent"}
    own_link = outbox.latest(email, OneTimeTokenPurpose.EMAIL_VERIFICATION)
    assert own_link is not None and own_link != stranger_link

    # The stranger's earlier link is dead, whichever password is offered.
    for password in (ATTACKER_PASSWORD, NEW_PASSWORD):
        old = await call(
            client,
            "POST",
            "/auth/verify-email",
            json={"token": stranger_link, "password": password},
        )
        assert old.status_code == 401
    ok = await call(
        client, "POST", "/auth/verify-email", json={"token": own_link, "password": NEW_PASSWORD}
    )
    assert ok.status_code == 200
    assert (await login(client, email, NEW_PASSWORD)).status_code == 200
    assert (await login(client, email, ATTACKER_PASSWORD)).status_code == 401


async def test_registering_an_active_or_invited_account_changes_nothing(
    client: httpx.AsyncClient, world: World, outbox: InMemoryTokenOutbox
) -> None:
    sent = len(outbox.sent)
    r = await call(
        client,
        "POST",
        "/auth/register",
        json=_sign_up(world.student.email, ATTACKER_PASSWORD, "X-1"),
    )
    assert r.status_code == 202
    assert len(outbox.sent) == sent
    assert (await login(client, world.student.email, world.password)).status_code == 200
    assert (await login(client, world.student.email, ATTACKER_PASSWORD)).status_code == 401


# ---- rate limiting cannot be dodged with forwarding headers ---------------------------------


@pytest_asyncio.fixture
async def limited_app(api_engine: AsyncEngine) -> FastAPI:
    return create_app(
        get_settings(),
        session_factory=create_session_factory(api_engine),
        delivery=InMemoryTokenOutbox(),
        limiter=SlidingWindowRateLimiter(3),
    )


async def test_auth_rate_limit_ignores_spoofed_forwarding_headers(limited_app: FastAPI) -> None:
    transport = httpx.ASGITransport(app=limited_app, client=("198.51.100.23", 1))
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as c:
        codes = []
        for i in range(5):
            spoof = f"192.0.2.{i + 1}"
            r = await c.post(
                f"{API}/auth/login",
                json={"email": "nobody@test.example", "password": "wrong-password-123"},
                headers={"X-Forwarded-For": spoof, "X-Real-IP": spoof, "Forwarded": f"for={spoof}"},
            )
            codes.append(r.status_code)
        assert codes == [401, 401, 401, 429, 429]
