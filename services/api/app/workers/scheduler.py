"""Periodic work: appointment reminders, sending notifications that leave the app, and
deleting AI companion conversations and safety events past their retention.

Runs inside the API when ``SCHEDULER_ENABLED=true``, or on its own:

    python -m app.workers.scheduler            # loop every SCHEDULER_INTERVAL_SECONDS
    python -m app.workers.scheduler --once     # one pass, for cron or a job runner

Every step is idempotent and safe to run from several processes at once (unique reminder
records, ``SKIP LOCKED`` deliveries), so running it twice never reminds anyone twice.
"""

import argparse
import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.companion import sweep_expired
from app.application.notifications import dispatch_due
from app.application.reminders import send_due_reminders
from app.application.safety_workflow import sweep_safety_events
from app.core.config import get_settings
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.notifications.providers import Providers, build_providers

log = logging.getLogger("mindmitra.scheduler")


async def run_once(session_factory: async_sessionmaker[AsyncSession], providers: Providers) -> None:
    reminded = await send_due_reminders(session_factory)
    result = await dispatch_due(session_factory, providers)
    async with session_factory() as db:
        expired = await sweep_expired(db)
    async with session_factory() as db:
        events = await sweep_safety_events(db)
    if (
        reminded
        or expired
        or events
        or result.sent
        or result.failed
        or result.retried
        or result.skipped
    ):
        log.info(
            "scheduler pass: reminded=%d sent=%d retried=%d failed=%d skipped=%d "
            "companion_expired=%d safety_events_expired=%d",
            reminded,
            result.sent,
            result.retried,
            result.failed,
            result.skipped,
            expired,
            events,
        )


async def run_forever(
    session_factory: async_sessionmaker[AsyncSession], providers: Providers, interval: float
) -> None:
    while True:
        try:
            await run_once(session_factory, providers)
        except Exception:  # one bad pass must not stop reminders for good
            log.exception("scheduler pass failed")
        await asyncio.sleep(interval)


async def _main(once: bool) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    providers = build_providers(settings.notification_email_provider)
    try:
        if once:
            await run_once(factory, providers)
        else:
            await run_forever(factory, providers, settings.scheduler_interval_seconds)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="run one pass and exit")
    asyncio.run(_main(parser.parse_args().once))
