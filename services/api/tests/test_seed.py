"""The synthetic seed: safe, realistic, deterministic."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.infrastructure.db import models as m
from app.infrastructure.db.seed import SeedConfig, SeedRefused, seed_database
from tests import helpers

_TLS_URL = "postgresql+asyncpg://u:p@db.internal:5432/x?ssl=require"


async def test_seed_populates_every_entity(session: AsyncSession) -> None:
    tables = [
        "iam.users",
        "iam.credentials",
        "org.institutions",
        "org.departments",
        "org.courses",
        "org.students",
        "org.teachers",
        "org.therapists",
        "org.administrators",
        "org.course_enrollments",
        "org.care_team_members",
        "wellness.mood_entries",
        "wellness.wellness_assessments",
        "wellness.stress_assessments",
        "wellness.sleep_entries",
        "wellness.journal_entries",
        "wellness.wellness_goals",
        "wellness.resources",
        "therapy.therapist_availability",
        "therapy.appointments",
        "therapy.therapy_sessions",
        "therapy.therapy_notes",
        "comm.messages",
        "ai.ai_conversations",
        "ai.ai_messages",
        "ai.recommendations",
        "safety.risk_alerts",
        "consent.consents",
        "notify.notifications",
        "audit.audit_logs",
    ]
    for t in tables:
        assert await helpers.count(session, t) > 0, f"{t} is empty"


async def test_seed_data_is_clearly_synthetic(session: AsyncSession) -> None:
    inst = await helpers.institution(session)
    assert inst.is_synthetic
    emails = (await session.execute(select(m.User.email))).scalars().all()
    assert all(e.endswith(".example") for e in emails)
    notes = (await session.execute(select(m.TherapyNote.body))).scalars().all()
    assert all(n.startswith("SYNTHETIC NOTE") for n in notes)
    excerpts = (await session.execute(select(m.RiskAlert.excerpt))).scalars().all()
    assert all("[SYNTHETIC FIXTURE]" in (e or "") for e in excerpts)


async def test_seed_respects_roles_and_relationships(session: AsyncSession) -> None:
    rows = (await session.execute(text("SELECT role FROM iam.users GROUP BY role"))).scalars().all()
    roles = set(rows)
    assert roles == {"student", "therapist", "teacher", "administrator"}
    # every appointment is between a student and their care-team therapist
    stray = await helpers.count(
        session,
        "therapy.appointments a",
        "NOT EXISTS (SELECT 1 FROM org.care_team_members c "
        "WHERE c.student_id = a.student_id AND c.therapist_id = a.therapist_id)",
    )
    assert stray == 0
    # journal shares only go to the student's own therapist and are a minority of entries
    assert await helpers.count(session, "wellness.journal_shares") < await helpers.count(
        session, "wellness.journal_entries"
    )


async def test_seed_refuses_to_run_twice(session: AsyncSession) -> None:
    with pytest.raises(SeedRefused, match="already exists"):
        await seed_database(session, SeedConfig(students=3))


async def test_seed_refuses_in_production(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", _TLS_URL)
    with pytest.raises(SeedRefused, match="development or test"):
        await seed_database(session, SeedConfig(students=3))


async def test_seed_refuses_in_staging(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("DATABASE_URL", _TLS_URL)
    with pytest.raises(SeedRefused, match="development or test"):
        await seed_database(session, SeedConfig(students=3))


async def test_seed_is_deterministic(make_database) -> None:  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime

    anchor = datetime(2026, 10, 8, 12, tzinfo=UTC)
    results = []
    for _ in range(2):
        url = await make_database()
        eng = create_async_engine(url)
        try:
            async with AsyncSession(eng, expire_on_commit=False) as s:
                res = await seed_database(
                    s,
                    SeedConfig(
                        students=6,
                        therapists=2,
                        teachers=2,
                        seed=7,
                        as_of=anchor,
                        password="deterministic-pw-1",
                    ),
                )
            async with AsyncSession(eng) as s:
                names = (
                    (await s.execute(select(m.User.full_name).order_by(m.User.email)))
                    .scalars()
                    .all()
                )
            results.append((res.counts, names))
        finally:
            await eng.dispose()
    assert results[0] == results[1]
