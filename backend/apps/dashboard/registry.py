"""Dashboard widget providers.

The dashboard response always contains every key in WIDGET_KEYS so the frontend
contract never changes. A key whose module is not built yet is `null` ("coming
soon"). Apps fill keys by registering a provider in their AppConfig.ready():

    dashboard.register("tasks_today", lambda user: [...])
"""
import logging
from typing import Callable

logger = logging.getLogger(__name__)

WIDGET_KEYS = [
    "tasks_today",          # Phase 2
    "overdue",              # Phase 2
    "upcoming_deadlines",   # Phase 2
    "unread_messages",      # Phase 3
    "pending_approvals",    # Phase 4
    "meetings_today",       # Phase 4
    "bookings_today",       # Phase 4
    "unread_notifications",
    "activity",
    "stats",
]

_providers: dict[str, Callable] = {}


def register(key: str, provider: Callable):
    if key not in WIDGET_KEYS:
        raise ValueError(f"Unknown dashboard widget key: {key}")
    _providers[key] = provider


def build(user) -> dict:
    data = {}
    for key in WIDGET_KEYS:
        provider = _providers.get(key)
        if provider is None:
            data[key] = None
            continue
        try:
            data[key] = provider(user)
        except Exception:  # one broken widget must not take down the dashboard
            logger.exception("Dashboard widget %s failed", key)
            data[key] = None
    return data
