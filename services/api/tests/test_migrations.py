"""Schema-level guarantees: migrations, conventions, foreign keys, indexes."""

import asyncio
from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from app.infrastructure.db.base import SCHEMAS, Base
from tests.conftest import alembic_config

EXPECTED_TABLES = {
    "iam": {"users", "credentials"},
    "org": {
        "institutions",
        "departments",
        "courses",
        "students",
        "teachers",
        "therapists",
        "administrators",
        "course_enrollments",
        "course_teachers",
        "care_team_members",
    },
    "wellness": {
        "mood_entries",
        "wellness_assessments",
        "stress_assessments",
        "sleep_entries",
        "journal_entries",
        "journal_shares",
        "wellness_goals",
        "resources",
    },
    "therapy": {"therapist_availability", "appointments", "therapy_sessions", "therapy_notes"},
    "comm": {"messages"},
    "ai": {"ai_conversations", "ai_messages", "recommendations"},
    "safety": {"risk_alerts"},
    "consent": {"consents"},
    "notify": {"notifications"},
    "audit": {"audit_logs"},
}


async def test_all_required_entities_exist(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT table_schema, table_name FROM information_schema.tables "
                    "WHERE table_schema = ANY(:s) AND table_type = 'BASE TABLE'"
                ),
                {"s": list(SCHEMAS)},
            )
        ).all()
    actual: dict[str, set[str]] = {}
    for schema, name in rows:
        actual.setdefault(schema, set()).add(name)
    assert actual == EXPECTED_TABLES


async def test_models_match_migrations(db_url: str) -> None:
    """`alembic check` fails if the models drift from the migration history."""
    await asyncio.to_thread(command.check, alembic_config(db_url))


async def test_downgrade_then_upgrade_roundtrip(
    make_database: Callable[[], "asyncio.Future[str]"],
) -> None:
    url = await make_database()
    cfg = alembic_config(url)
    await asyncio.to_thread(command.downgrade, cfg, "base")
    eng = create_async_engine(url)
    try:
        async with eng.connect() as conn:
            n = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_schema = ANY(:s)"
                    ),
                    {"s": list(SCHEMAS)},
                )
            ).scalar_one()
        assert n == 0
    finally:
        await eng.dispose()
    await asyncio.to_thread(command.upgrade, cfg, "head")
    await asyncio.to_thread(command.check, cfg)


async def test_every_table_has_timestamps(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT table_schema||'.'||table_name, "
                    "bool_or(column_name='created_at'), bool_or(column_name='updated_at') "
                    "FROM information_schema.columns WHERE table_schema = ANY(:s) "
                    "GROUP BY table_schema, table_name"
                ),
                {"s": list(SCHEMAS)},
            )
        ).all()
    missing = [t for t, c, u in rows if t != "audit.audit_logs" and not (c and u)]
    assert not missing, f"tables without created_at/updated_at: {missing}"
    audit = next(r for r in rows if r[0] == "audit.audit_logs")
    assert not audit[2], "audit rows are immutable, so they carry no updated_at"


async def test_primary_keys_are_uuids(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT n.nspname||'.'||c.relname, a.attname, format_type(a.atttypid, NULL)
                    FROM pg_constraint k
                    JOIN pg_class c ON c.oid = k.conrelid
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(k.conkey)
                    WHERE k.contype = 'p' AND n.nspname = ANY(:s)
                    """
                ),
                {"s": list(SCHEMAS)},
            )
        ).all()
    bad = [(t, col, typ) for t, col, typ in rows if typ != "uuid" and t != "audit.audit_logs"]
    assert not bad, bad


async def test_every_foreign_key_has_explicit_delete_policy(engine: AsyncEngine) -> None:
    """No FK may rely on the implicit NO ACTION default: each is CASCADE/RESTRICT/SET NULL."""
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT conname, confdeltype FROM pg_constraint k
                    JOIN pg_namespace n ON n.oid = k.connamespace
                    WHERE k.contype = 'f' AND n.nspname = ANY(:s)
                    """
                ),
                {"s": list(SCHEMAS)},
            )
        ).all()
    assert rows
    implicit = [name for name, t in rows if t == "a"]
    assert not implicit, implicit


async def test_every_foreign_key_column_is_indexed(engine: AsyncEngine) -> None:
    """The leading column of each FK must lead some index (or the PK) for join/delete speed."""
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT n.nspname||'.'||c.relname AS tbl, k.conname
                    FROM pg_constraint k
                    JOIN pg_class c ON c.oid = k.conrelid
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE k.contype = 'f' AND n.nspname = ANY(:s)
                    AND NOT EXISTS (
                        SELECT 1 FROM pg_index i
                        WHERE i.indrelid = k.conrelid
                          AND i.indkey[0] = k.conkey[1]
                    )
                    """
                ),
                {"s": list(SCHEMAS)},
            )
        ).all()
    assert not rows, f"unindexed foreign keys: {rows}"


def test_model_tables_cover_every_expected_table() -> None:
    tables = {f"{t.schema}.{t.name}" for t in Base.metadata.tables.values()}
    expected = {f"{s}.{n}" for s, names in EXPECTED_TABLES.items() for n in names}
    assert tables == expected
