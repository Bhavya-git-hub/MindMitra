"""Async engine and session management."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings


def create_engine(settings: Settings | None = None) -> AsyncEngine:
    s = settings or get_settings()
    return create_async_engine(
        s.database_url.get_secret_value(),
        echo=s.db_echo,
        pool_size=s.db_pool_size,
        max_overflow=s.db_max_overflow,
        pool_timeout=s.db_pool_timeout_seconds,
        pool_pre_ping=True,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@asynccontextmanager
async def session_scope(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    """One unit of work: commit on success, roll back on any error."""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


async def set_rls_context(
    session: AsyncSession, *, user_id: str, institution_id: str, role: str
) -> None:
    """Set transaction-local context variables for row-level-security policies.

    Policies are introduced with the authorization phase; the hook exists now so the
    connection layer is complete. ``set_config(..., true)`` is transaction-local, which is
    safe with pooled/PgBouncer transaction-mode connections.
    """
    from sqlalchemy import text

    await session.execute(
        text(
            "SELECT set_config('app.user_id', :u, true), "
            "set_config('app.institution_id', :i, true), set_config('app.role', :r, true)"
        ),
        {"u": user_id, "i": institution_id, "r": role},
    )
