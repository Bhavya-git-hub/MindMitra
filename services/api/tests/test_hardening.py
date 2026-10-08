"""Configuration, logging and audit-trail hardening found in the database-layer review."""

import datetime as dt
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.crypto import generate_key
from app.infrastructure.db import models as m
from app.infrastructure.db.audit import (
    AuditDetailsError,
    append_audit_event,
    validate_details,
    verify_chain,
)
from app.infrastructure.db.enums import AlertStatus, AuditOutcome
from app.infrastructure.db.session import create_engine
from tests import helpers
from tests.test_constraints import NOW, _alert, rejected

PLAIN = "postgresql+asyncpg://u:p@db.internal:5432/x"


def _settings(**kw: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": "development",
        "database_url": PLAIN,
        "field_encryption_key": generate_key(),
    }
    values.update(kw)
    if values["app_env"] is None:
        del values["app_env"]
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


# ---- settings -----------------------------------------------------------------------------


def test_app_env_has_no_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    with pytest.raises(ValidationError, match="app_env"):
        _settings(app_env=None)


@pytest.mark.parametrize("env", ["staging", "production"])
def test_tls_is_required_outside_development(env: str) -> None:
    with pytest.raises(ValidationError, match="TLS"):
        _settings(app_env=env)
    with pytest.raises(ValidationError, match="TLS"):
        _settings(app_env=env, database_url=PLAIN + "?ssl=disable")
    assert _settings(app_env=env, database_url=PLAIN + "?ssl=require").app_env == env
    assert _settings(app_env=env, database_url=PLAIN + "?ssl=verify-full").app_env == env


def test_tls_not_forced_for_local_development() -> None:
    assert _settings(app_env="development").app_env == "development"
    assert _settings(app_env="test").app_env == "test"


@pytest.mark.parametrize("bad", ["change-me", "", "AAAA", generate_key()[:-4]])
def test_encryption_key_is_validated_at_startup(bad: str) -> None:
    with pytest.raises(ValidationError, match="FIELD_ENCRYPTION_KEY"):
        _settings(field_encryption_key=bad)


def test_database_url_must_use_asyncpg() -> None:
    with pytest.raises(ValidationError, match="asyncpg"):
        _settings(database_url="postgresql://u:p@h/db")


@pytest.mark.parametrize(
    ("env", "allowed"),
    [("development", True), ("test", True), ("staging", False), ("production", False)],
)
def test_seeding_is_only_allowed_in_development_and_test(env: str, allowed: bool) -> None:
    url = PLAIN + ("" if allowed else "?ssl=require")
    assert _settings(app_env=env, database_url=url).allows_seeding is allowed


def test_secrets_are_not_in_repr() -> None:
    s = _settings()
    assert "u:p@" not in repr(s)
    assert s.field_encryption_key.get_secret_value() not in repr(s)


# ---- logging -------------------------------------------------------------------------------


async def test_sql_errors_do_not_leak_bound_parameters(db_url: str) -> None:
    """Parameters can hold PII; `hide_parameters=True` keeps them out of exception text/logs."""
    engine = create_engine(_settings(database_url=db_url))
    secret = "student-journal-text-0123456789"
    try:
        async with engine.connect() as conn:
            with pytest.raises(DBAPIError) as info:
                await conn.execute(
                    text("SELECT cast(:v AS text), 1 / cast(:z AS int)"), {"v": secret, "z": 0}
                )
        assert "division by zero" in str(info.value)
        assert secret not in str(info.value)
    finally:
        await engine.dispose()


# ---- audit details guard ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "details",
    [
        {"body": "hi"},
        {"Content": "hi"},
        {"nested": {"note": "x"}},
        {"items": [{"password": "x"}]},
        {"email": "a@b.example"},
        {"blob": "x" * 201},
    ],
)
def test_audit_details_reject_content_and_secrets(details: dict[str, Any]) -> None:
    with pytest.raises(AuditDetailsError):
        validate_details(details)


def test_audit_details_accept_metadata() -> None:
    validate_details({"scope": "therapy_notes", "count": 3, "ids": ["a", "b"], "flag": True})


async def test_audit_append_rejects_bad_details_before_writing(session: AsyncSession) -> None:
    inst = await helpers.institution(session)
    before = await helpers.count(session, "audit.audit_logs")
    with pytest.raises(AuditDetailsError):
        await append_audit_event(
            session,
            institution_id=inst.id,
            action="message.read",
            outcome=AuditOutcome.ALLOWED,
            details={"body": "do not store me"},
        )
    assert await helpers.count(session, "audit.audit_logs") == before
    await append_audit_event(
        session,
        institution_id=inst.id,
        action="message.read",
        outcome=AuditOutcome.ALLOWED,
        details={"count": 1},
    )
    assert await verify_chain(session, inst.id) is None


# ---- risk alert workflow ----------------------------------------------------------------------


async def test_automatic_escalation_does_not_require_acknowledgement(session: AsyncSession) -> None:
    """Regression: ESCALATED used to demand `acknowledged_at`, blocking automated escalation."""
    s = await helpers.any_student(session)
    session.add(_alert(s, status=AlertStatus.ESCALATED))
    await session.flush()
    for status in (AlertStatus.ACKNOWLEDGED, AlertStatus.IN_PROGRESS):
        await rejected(session, _alert(s, status=status), match="acknowledged_before_progress")
    session.add(_alert(s, status=AlertStatus.ACKNOWLEDGED, acknowledged_at=NOW))
    await session.flush()


async def test_alert_assignee_cannot_be_hard_deleted(session: AsyncSession) -> None:
    """RESTRICT (not SET NULL): clinical staff with assigned alerts follow the retention flow."""
    s = await helpers.any_student(session)
    th = await helpers.therapist_in(session, await helpers.institution(session))
    alert = _alert(s, assigned_to=th.user_id)
    session.add(alert)
    await session.flush()
    with pytest.raises(DBAPIError, match="fk_risk_alerts_assigned_to_institution_id_therapists"):
        async with session.begin_nested():
            await session.execute(
                text("DELETE FROM org.therapists WHERE user_id = :u"), {"u": th.user_id}
            )


# ---- updated_at is maintained by the database -------------------------------------------------


async def test_raw_sql_update_refreshes_updated_at(session: AsyncSession) -> None:
    row = await helpers.first(session, select(m.MoodEntry))
    before = (
        await session.execute(
            text("SELECT updated_at FROM wellness.mood_entries WHERE id = :i"), {"i": row.id}
        )
    ).scalar_one()
    after = (
        await session.execute(
            text(
                "UPDATE wellness.mood_entries SET mood_score = mood_score, "
                "updated_at = '2000-01-01' WHERE id = :i RETURNING updated_at"
            ),
            {"i": row.id},
        )
    ).scalar_one()
    assert after > before, "trigger must override a stale/backdated updated_at"
    assert after <= dt.datetime.now(dt.UTC) + dt.timedelta(minutes=1)


async def test_every_table_with_updated_at_has_the_trigger(session: AsyncSession) -> None:
    missing = (
        (
            await session.execute(
                text(
                    """
                SELECT c.table_schema||'.'||c.table_name
                FROM information_schema.columns c
                WHERE c.column_name = 'updated_at'
                  AND c.table_schema IN ('iam','org','wellness','therapy','comm','ai','safety',
                                         'consent','notify')
                  AND NOT EXISTS (
                      SELECT 1 FROM pg_trigger t
                      WHERE t.tgrelid = (c.table_schema||'.'||c.table_name)::regclass
                        AND t.tgfoid = 'public.set_updated_at'::regproc
                        AND NOT t.tgisinternal)
                """
                )
            )
        )
        .scalars()
        .all()
    )
    assert not missing, f"tables with updated_at but no set_updated_at trigger: {missing}"
