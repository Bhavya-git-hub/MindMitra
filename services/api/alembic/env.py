"""Alembic environment (async). The URL is read from DATABASE_URL, never from alembic.ini."""

import asyncio
import os
from logging.config import fileConfig
from typing import Any

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import app.infrastructure.db.models  # noqa: F401  (registers models on metadata)
from alembic import context
from app.infrastructure.db.base import SCHEMAS, Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    # An explicit option (used by tests) wins over the environment.
    url = config.get_main_option("sqlalchemy.url") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def _include_name(name: str | None, type_: str, parent_names: dict[str, Any]) -> bool:
    if type_ == "schema":
        return name in SCHEMAS
    return True


def _render_item(type_: str, obj: Any, autogen_context: Any) -> str | bool:
    """Migrations must not import application code: render EncryptedText as plain BYTEA."""
    if type_ == "type" and obj.__class__.__name__ == "EncryptedText":
        return "sa.LargeBinary()"
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        include_name=_include_name,
        version_table_schema="public",
        compare_type=True,
        render_item=_render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=_include_name,
        version_table_schema="public",
        compare_type=True,
        compare_server_default=False,
        render_item=_render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _url()
    engine = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
