"""Test fixtures: a throwaway PostgreSQL database, migrated with Alembic and seeded once.

Set TEST_DATABASE_URL to a server URL the test user may CREATE DATABASE on, e.g.
``postgresql+asyncpg://user:pass@localhost:5432/postgres``. Each run creates and drops its own
database; the named database in the URL is only used for the admin connection.
Tests that need superuser powers (disabling triggers, creating roles) assume a local test
cluster and skip otherwise.
"""

import asyncio
import os
import secrets
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from alembic import command

_ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
if not _ADMIN_URL:
    pytest.exit(
        "TEST_DATABASE_URL is not set (a postgresql+asyncpg:// URL for a disposable test server)",
        returncode=2,
    )

# Settings are read from the environment on first use; set safe test values before any import.
os.environ["APP_ENV"] = "test"
from app.core.crypto import generate_key  # noqa: E402

os.environ.setdefault("FIELD_ENCRYPTION_KEY", generate_key())  # fresh random key per run
os.environ["DATABASE_URL"] = _ADMIN_URL  # replaced per-run below

from app.core.config import get_settings  # noqa: E402
from app.infrastructure.db.seed import SeedConfig, SeedResult, seed_database  # noqa: E402
from app.infrastructure.db.types import reset_cipher  # noqa: E402

API_ROOT = Path(__file__).resolve().parent.parent
SEED_PASSWORD = secrets.token_urlsafe(18)  # random per run; only protects throwaway test data


def alembic_config(url: str) -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def url_for(db_name: str) -> str:
    assert _ADMIN_URL is not None
    return make_url(_ADMIN_URL).set(database=db_name).render_as_string(hide_password=False)


async def _admin(sql: str) -> None:
    assert _ADMIN_URL is not None
    eng = create_async_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        async with eng.connect() as conn:
            await conn.execute(text(sql))
    finally:
        await eng.dispose()


@pytest_asyncio.fixture(scope="session")
async def make_database() -> AsyncIterator[Callable[[], "asyncio.Future[str]"]]:
    """Factory that creates a fresh, migrated database and returns its URL. Cleaned up at end."""
    created: list[str] = []

    async def _make() -> str:
        name = f"mm_test_{uuid.uuid4().hex[:10]}"
        await _admin(f'CREATE DATABASE "{name}"')
        created.append(name)
        url = url_for(name)
        await asyncio.to_thread(command.upgrade, alembic_config(url), "head")
        return url

    yield _make  # type: ignore[misc]
    for name in created:
        await _admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest_asyncio.fixture(scope="session")
async def db_url(make_database: Callable[[], "asyncio.Future[str]"]) -> str:
    return await make_database()


@pytest_asyncio.fixture(scope="session")
async def engine(db_url: str) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(db_url)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture(scope="session")
async def seeded(engine: AsyncEngine) -> SeedResult:
    """Seed once (committed). Tests that mutate data do so inside rolled-back transactions."""
    get_settings.cache_clear()
    reset_cipher()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        return await seed_database(s, SeedConfig(students=30, therapists=3, password=SEED_PASSWORD))


@pytest_asyncio.fixture
async def session(engine: AsyncEngine, seeded: SeedResult) -> AsyncIterator[AsyncSession]:
    """A session inside an outer transaction that is always rolled back."""
    async with engine.connect() as conn:
        trans = await conn.begin()
        async with AsyncSession(
            bind=conn,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
            autoflush=False,
        ) as s:
            yield s
        await trans.rollback()


@pytest.fixture(autouse=True)
def _fresh_settings() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
