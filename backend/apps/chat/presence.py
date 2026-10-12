"""Who is online, and which conversation each open tab is showing.

Each WebSocket connection is an entry in the user's cache record: {channel_name: {"exp", "viewing"}}.
Entries expire CONNECTION_TTL seconds after the last sign of life (connect, ping, viewing change),
so a tab that vanished without a clean disconnect (crash, lost network) drops out on its own.
Clients ping every 30 seconds. The cache is Redis whenever REDIS_URL is set, so every server
process sees the same picture.
"""
import time

from apps.core.safe_cache import safe_cache

CONNECTION_TTL = 75  # seconds without a ping before a connection counts as gone
_KEY = "chat:presence:{}"


def _key(user_id) -> str:
    return _KEY.format(user_id)


def _live(record: dict | None, now: float) -> dict:
    return {name: entry for name, entry in (record or {}).items() if entry.get("exp", 0) > now}


def _store(user_id, record: dict):
    if record:
        safe_cache.set(_key(user_id), record, timeout=CONNECTION_TTL * 2)
    else:
        safe_cache.delete(_key(user_id))


def touch(user_id, channel_name: str, *, viewing=..., remove=False) -> tuple[bool, bool]:
    """Update one connection. Returns (online before, online after)."""
    now = time.time()
    record = _live(safe_cache.get(_key(user_id)), now)
    before = bool(record)
    if remove:
        record.pop(channel_name, None)
    else:
        entry = record.get(channel_name, {"viewing": None})
        entry["exp"] = now + CONNECTION_TTL
        if viewing is not ...:
            entry["viewing"] = viewing
        record[channel_name] = entry
    _store(user_id, record)
    return before, bool(record)


def is_online(user_id) -> bool:
    return bool(_live(safe_cache.get(_key(user_id)), time.time()))


def online_ids(user_ids) -> set[int]:
    user_ids = list(user_ids)
    if not user_ids:
        return set()
    now = time.time()
    records = safe_cache.get_many([_key(u) for u in user_ids])
    return {u for u in user_ids if _live(records.get(_key(u)), now)}


def is_viewing(user_id, conversation_id) -> bool:
    """True if any of the user's open, visible tabs shows this conversation right now."""
    record = _live(safe_cache.get(_key(user_id)), time.time())
    return any(entry.get("viewing") == conversation_id for entry in record.values())
