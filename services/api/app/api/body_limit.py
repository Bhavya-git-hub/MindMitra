"""A cap on the size of a request body, enforced before anything parses it.

Without it a single anonymous request could make the API buffer and parse a body of any size
(a 50 MB JSON body was read in full before the 401). The largest legitimate body is a few tens of
kilobytes (the longest text field is 20,000 characters), so the cap leaves ample room.
"""

from typing import Final

from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_BODY_BYTES: Final = 512 * 1024


class BodySizeLimit:
    """Refuses a declared ``Content-Length`` over the cap at once, and stops reading a body
    sent without one (chunked) as soon as it passes the cap. Both answer 413 before the app
    sees the request."""

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None:
            try:
                too_big = int(declared) > self.max_bytes
            except ValueError:
                too_big = True
            if too_big:
                await _refuse(send)
                return

        # Read the body here (it is small by definition) so an oversized chunked body can be
        # refused before the app starts, then hand the app the same bytes.
        chunks: list[bytes] = []
        seen = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":  # the client went away
                await self.app(scope, _replay([], message, receive), send)
                return
            chunk = message.get("body", b"")
            seen += len(chunk)
            if seen > self.max_bytes:
                await _refuse(send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        await self.app(scope, _replay(chunks, None, receive), send)


def _replay(chunks: list[bytes], pending: Message | None, receive: Receive) -> Receive:
    sent = False

    async def replayed() -> Message:
        nonlocal sent
        if not sent:
            sent = True
            if pending is not None:
                return pending
            return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
        return await receive()  # after the body: wait for a disconnect, as the server would

    return replayed


async def _refuse(send: Send) -> None:
    body = (
        b'{"type":"about:blank","title":"Content Too Large","status":413,'
        b'"detail":"The request is too large."}'
    )
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/problem+json"),
                (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"no-store"),
                (b"x-content-type-options", b"nosniff"),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
