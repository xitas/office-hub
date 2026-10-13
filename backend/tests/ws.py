"""WebSocket helpers for tests: connect with a ticket, wait for a specific event, check nothing arrives.

Events can arrive in any order (presence changes, unread counts, notifications), so tests wait for
the event they care about up to a deadline instead of reading "the next message". Waiting returns
as soon as the event arrives; the deadline only matters when something is wrong, and then the
failure says what was expected and what came instead.
"""
import asyncio
import time
from contextlib import asynccontextmanager

from channels.testing import WebsocketCommunicator

from apps.core.ws_auth import issue_ticket
from config.asgi import application

DEADLINE = 5  # seconds to wait for an expected event
QUIET = 0.4  # seconds of silence that count as "nothing arrived"
ORIGIN = [(b"origin", b"http://localhost")]


async def connect(user) -> WebsocketCommunicator:
    """An authenticated connection, past the unread count the server sends first."""
    ws = WebsocketCommunicator(application, f"/ws/notifications/?ticket={issue_ticket(user)}", headers=ORIGIN)
    connected, _ = await ws.connect(timeout=DEADLINE)
    assert connected, f"WebSocket for {user.email} was refused"
    first = await ws.receive_json_from(timeout=DEADLINE)
    assert first["type"] == "unread_count", first
    return ws


@asynccontextmanager
async def connected(*users):
    """Connections that are always closed, even when the test fails (no tasks leak into the next test)."""
    sockets = []
    try:
        for user in users:
            sockets.append(await connect(user))
        yield sockets
    finally:
        for ws in sockets:
            await ws.disconnect()


def _matches(data: dict, event: str) -> bool:
    return data.get("event") == event or data.get("type") == event


async def next_event(ws, event: str, *, timeout: float = DEADLINE, where=None) -> dict:
    """The next message whose chat `event` (or `type`, e.g. "notification") is `event`; others are skipped.
    `where` narrows it further, e.g. ``where=lambda e: e["user"] == 5``."""
    deadline = time.monotonic() + timeout
    seen = []
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError(f"no {event!r} event within {timeout}s; received: {seen}")
        try:
            data = await ws.receive_json_from(timeout=remaining)
        except asyncio.TimeoutError:
            raise AssertionError(f"no {event!r} event within {timeout}s; received: {seen}") from None
        if _matches(data, event) and (where is None or where(data)):
            return data
        seen.append(data.get("event") or data.get("type"))


async def no_event(ws, event: str, *, quiet: float = QUIET):
    """No message of this kind arrives (others are fine) before the connection is quiet for `quiet` seconds."""
    while not await ws.receive_nothing(timeout=quiet):
        data = await ws.receive_json_from()
        assert not _matches(data, event), f"unexpected {event!r} event: {data}"
