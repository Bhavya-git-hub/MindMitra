"""Security regression tests for the real-time channel (security audit 2026-10).

The handshake, origin and per-user tests live in ``test_notifications_realtime.py``; these cover
gaps found in the audit.
"""

import asyncio
import contextlib
import uuid

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import realtime
from app.api.deps import AppState
from tests.api_world import World
from tests.student_helpers import new_student
from tests.test_notifications_realtime import FakeSocket, _state, _until

pytestmark = pytest.mark.asyncio


async def _keep_publishing(state: AppState, user_id: uuid.UUID, every: float) -> None:
    hub = state.hub
    n = 0
    while True:
        hub.publish(user_id, {"type": "notification", "n": n})
        n += 1
        await asyncio.sleep(every)


async def test_a_steady_event_stream_does_not_keep_a_signed_out_socket_open(
    client: httpx.AsyncClient,
    api_db: AsyncSession,
    world: World,
    api_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revalidation used to run only after ``REVALIDATE_EVERY`` seconds with *no* event. Events
    arriving more often than that (an active chat, the victim reading notifications on another
    device) kept a revoked session's socket open, receiving events, indefinitely."""
    monkeypatch.setattr(realtime, "REVALIDATE_EVERY", 0.2)
    state = _state(api_app)
    s = await new_student(client, api_db, world)
    ws = FakeSocket(state)
    task = asyncio.ensure_future(realtime.realtime_socket(ws))
    ws.say({"type": "auth", "token": s.token})
    await _until(lambda: {"type": "ready"} in ws.sent)
    feeder = asyncio.ensure_future(_keep_publishing(state, s.id, 0.02))
    try:
        await _until(lambda: len(ws.sent) > 3)  # events are flowing
        assert (await s.post("/auth/logout")).status_code == 204
        await asyncio.wait_for(task, 3)
    finally:
        feeder.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await feeder
        if not task.done():
            ws.incoming.put_nowait(None)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(task, 3)
    assert ws.closed == realtime.CLOSE_UNAUTHENTICATED
    assert state.hub.connection_count(s.id) == 0


async def test_a_live_session_keeps_receiving_events_across_rechecks(
    client: httpx.AsyncClient,
    api_db: AsyncSession,
    world: World,
    api_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scheduled re-check must not drop a valid connection or its events."""
    monkeypatch.setattr(realtime, "REVALIDATE_EVERY", 0.05)
    state = _state(api_app)
    s = await new_student(client, api_db, world)
    ws = FakeSocket(state)
    task = asyncio.ensure_future(realtime.realtime_socket(ws))
    ws.say({"type": "auth", "token": s.token})
    await _until(lambda: {"type": "ready"} in ws.sent)
    feeder = asyncio.ensure_future(_keep_publishing(state, s.id, 0.01))
    try:
        await asyncio.sleep(0.4)  # several re-checks while events flow
        assert not task.done()
    finally:
        feeder.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await feeder
        ws.incoming.put_nowait(None)
        await asyncio.wait_for(task, 3)
    assert ws.closed == 1000
    assert sum(1 for e in ws.sent if e.get("type") == "notification") > 5
