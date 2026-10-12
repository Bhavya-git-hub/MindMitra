"""The real-time channel: one WebSocket per open tab, server-to-client events only.

Protocol (JSON text frames):

1. The client connects to ``/api/v1/ws`` and, within ``AUTH_TIMEOUT``, sends
   ``{"type": "auth", "token": "<access token>"}``. The token travels in the first frame, never
   in the URL, so it does not end up in proxy or server logs.
2. The server answers ``{"type": "ready"}`` and then sends events for this user only:
   ``notification``, ``notifications_read``, ``message``, ``message_read`` and ``appointment``.
   Events hold identifiers and fixed words; the client fetches content through the REST API,
   which applies the same authorization as always.
3. The client may send ``{"type": "ping"}`` and gets ``{"type": "pong"}``.

The session behind the token is checked again every ``REVALIDATE_EVERY``, so signing out,
suspension or a role change closes the socket. Close codes: 4401 not signed in, 4403 origin not
allowed, 4429 too many connections, 1013 the client fell too far behind.
"""

import asyncio
import contextlib
import json
import logging
from typing import Any, Final, Protocol

from starlette.websockets import WebSocket, WebSocketDisconnect

from app.api.deps import AppState, principal_from_token
from app.domain.auth.policies import Principal
from app.infrastructure.realtime_hub import Connection

log = logging.getLogger("mindmitra.realtime")

AUTH_TIMEOUT: Final = 10.0
REVALIDATE_EVERY: Final = 60.0
MAX_FRAME: Final = 4096

CLOSE_UNAUTHENTICATED: Final = 4401
CLOSE_ORIGIN: Final = 4403
CLOSE_TOO_MANY: Final = 4429
CLOSE_TRY_AGAIN: Final = 1013


class Socket(Protocol):
    """The parts of Starlette's ``WebSocket`` this handler uses (tests pass a fake)."""

    @property
    def app(self) -> Any: ...

    @property
    def headers(self) -> Any: ...

    async def accept(self) -> None: ...

    async def receive_text(self) -> str: ...

    async def send_text(self, data: str) -> None: ...

    async def close(self, code: int = 1000) -> None: ...


def _state(ws: Socket) -> AppState:
    state: AppState = ws.app.state.mm
    return state


async def _send(ws: Socket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload, separators=(",", ":")))


async def _still_valid(state: AppState, token: str) -> bool:
    async with state.session_factory() as db:
        return await principal_from_token(db, state.codec, token) is not None


async def _reader(ws: Socket) -> None:
    """Answers pings; returns when the client goes away."""
    while True:
        raw = await ws.receive_text()
        if len(raw) > MAX_FRAME:
            return
        with contextlib.suppress(ValueError):
            frame = json.loads(raw)
            if isinstance(frame, dict) and frame.get("type") == "ping":
                await _send(ws, {"type": "pong"})


async def _writer(ws: Socket, conn: Connection, state: AppState, token: str) -> int:
    """Forwards events; returns the close code when the connection must end.

    The session is re-checked on a fixed schedule, whether or not events are flowing: a steady
    stream of events (an active chat, notifications read on another device) must not keep a
    signed-out, suspended or expired session's socket open. An event that is due when the check
    fails is dropped, not delivered.
    """
    loop = asyncio.get_running_loop()
    next_check = loop.time() + REVALIDATE_EVERY
    while True:
        payload: dict[str, Any] | None = None
        wait = next_check - loop.time()
        if wait > 0:
            with contextlib.suppress(TimeoutError):
                payload = await asyncio.wait_for(conn.queue.get(), wait)
        if loop.time() >= next_check:
            if not await _still_valid(state, token):
                return CLOSE_UNAUTHENTICATED
            next_check = loop.time() + REVALIDATE_EVERY
        if payload is None:
            continue
        if conn.overflowed:
            return CLOSE_TRY_AGAIN
        await _send(ws, payload)


async def realtime_socket(ws: Socket) -> None:
    state = _state(ws)
    allowed = state.settings.cors_origin_list
    origin = ws.headers.get("origin")
    # Browsers always send Origin on a WebSocket; refusing others stops a page on another site
    # from riding a signed-in user's connection. Non-browser clients send none.
    if allowed and origin is not None and origin not in allowed:
        await ws.close(code=CLOSE_ORIGIN)
        return
    await ws.accept()
    holder: dict[str, str] = {}  # the token, kept only for the periodic re-check
    try:
        principal = await _authenticate(ws, state, holder)
    except WebSocketDisconnect:
        return
    if principal is None:
        await ws.close(code=CLOSE_UNAUTHENTICATED)
        return
    conn = state.hub.register(principal.user_id)
    if conn is None:
        await ws.close(code=CLOSE_TOO_MANY)
        return
    code = 1000
    reader = asyncio.ensure_future(_reader(ws))
    writer = asyncio.ensure_future(_writer(ws, conn, state, holder["token"]))
    try:
        await _send(ws, {"type": "ready"})
        done, _ = await asyncio.wait({reader, writer}, return_when=asyncio.FIRST_COMPLETED)
        if writer in done and not writer.cancelled() and writer.exception() is None:
            code = writer.result()
    except WebSocketDisconnect:
        pass
    finally:
        for task in (reader, writer):
            task.cancel()
        for task in (reader, writer):
            with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect, Exception):
                await task
        state.hub.unregister(conn)
    with contextlib.suppress(Exception):  # the client may already be gone
        await ws.close(code=code)


async def _authenticate(ws: Socket, state: AppState, holder: dict[str, str]) -> Principal | None:
    try:
        raw = await asyncio.wait_for(ws.receive_text(), AUTH_TIMEOUT)
    except TimeoutError:
        return None
    if len(raw) > MAX_FRAME:
        return None
    try:
        first = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(first, dict) or first.get("type") != "auth":
        return None
    token = first.get("token")
    if not isinstance(token, str) or not token:
        return None
    async with state.session_factory() as db:
        principal = await principal_from_token(db, state.codec, token)
    if principal is not None:
        holder["token"] = token
    return principal


async def websocket_endpoint(websocket: WebSocket) -> None:
    """Mounted at ``/api/v1/ws`` (see ``WEBSOCKET_ROUTES`` in ``app.api.main``)."""
    await realtime_socket(websocket)
