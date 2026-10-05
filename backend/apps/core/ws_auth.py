"""WebSocket authentication with short-lived, single-use tickets.

Browsers cannot set an Authorization header on a WebSocket, and putting the JWT
in the URL leaks a reusable credential into proxy/server logs. Instead the client
calls POST /api/v1/auth/ws-ticket/ (normal JWT auth) and connects with
``?ticket=<value>``. A ticket is random, valid for TICKET_TTL seconds, stored
hashed in the shared cache, and deleted on first use — a logged ticket is useless.
"""
import hashlib
import secrets
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache

TICKET_TTL = 30  # seconds
_PREFIX = "ws-ticket:"


def _key(ticket: str) -> str:
    return _PREFIX + hashlib.sha256(ticket.encode()).hexdigest()


def issue_ticket(user) -> str:
    ticket = secrets.token_urlsafe(32)
    cache.set(_key(ticket), user.pk, timeout=TICKET_TTL)
    return ticket


def redeem_ticket(ticket: str):
    """Returns the user id once; any later attempt (or an expired ticket) returns None."""
    if not ticket or len(ticket) > 128:
        return None
    key = _key(ticket)
    user_id = cache.get(key)
    # delete() reports whether *this* call removed the key, so two racing redeems can't both win.
    if user_id is None or not cache.delete(key):
        return None
    return user_id


@database_sync_to_async
def _user_for_ticket(ticket):
    user_id = redeem_ticket(ticket)
    if user_id is None:
        return AnonymousUser()
    return get_user_model().objects.filter(pk=user_id, is_active=True).first() or AnonymousUser()


class TicketAuthMiddleware(BaseMiddleware):
    """Authenticates WebSocket connections with ``?ticket=<single-use ticket>``."""

    async def __call__(self, scope, receive, send):
        params = parse_qs(scope.get("query_string", b"").decode())
        ticket = params.get("ticket", [None])[0]
        scope["user"] = await _user_for_ticket(ticket) if ticket else AnonymousUser()
        return await super().__call__(scope, receive, send)
