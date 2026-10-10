"""A cache that keeps working when Redis is down.

The shared cache (Redis when REDIS_URL is set) backs rate limits, WebSocket tickets and cached
settings. If Redis stops, a raw cache call raises and would turn sign-in into a server error.
`safe_cache` tries the shared cache first and, on a connection error, falls back to a small
in-process cache (logged at most once a minute). Limits then apply per server process until Redis
is back, which is better than locking everybody out.
"""
import logging
import time

from django.core.cache import cache
from django.core.cache.backends.locmem import LocMemCache

logger = logging.getLogger(__name__)

_fallback = LocMemCache("crm-fallback", {"TIMEOUT": 300, "OPTIONS": {"MAX_ENTRIES": 10000}})
_last_warning = 0.0


def _warn(exc):
    global _last_warning
    now = time.monotonic()
    if now - _last_warning > 60:
        _last_warning = now
        logger.warning("Shared cache unavailable (%s); using the in-process fallback.", exc.__class__.__name__)


class SafeCache:
    """Subset of the cache API used by the app (and by DRF throttles)."""

    def _call(self, name, *args, **kwargs):
        try:
            return getattr(cache, name)(*args, **kwargs)
        except Exception as exc:  # redis.ConnectionError, TimeoutError, ...
            _warn(exc)
            return getattr(_fallback, name)(*args, **kwargs)

    def get(self, key, default=None):
        return self._call("get", key, default)

    def set(self, key, value, timeout=None):
        return self._call("set", key, value, timeout)

    def add(self, key, value, timeout=None):
        return self._call("add", key, value, timeout)

    def delete(self, key):
        return self._call("delete", key)

    @staticmethod
    def available() -> bool:
        """True if the shared cache answers right now."""
        try:
            cache.get("crm:ping")
            return True
        except Exception as exc:
            _warn(exc)
            return False


safe_cache = SafeCache()
