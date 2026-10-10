"""Per-account sign-in protection, on top of the per-IP rate limit.

Failed sign-ins are counted per email address (whether or not an account exists, so responses
never reveal which emails are registered). From the 5th failure in a row, each further attempt
must wait: 30 s, then 1 min, 5 min, and at most 15 min. Accounts are never locked for good. A
successful sign-in or a password reset clears the count. The account owner is notified (in-app
and by email) when it happens, at most once an hour.

State lives in the shared cache (Redis). If Redis is down it is kept in the database instead.
"""
import hashlib
import logging
import time

from django.core.cache import cache
from django.utils.translation import gettext_noop as N_

logger = logging.getLogger(__name__)

THRESHOLD = 5
DELAYS = [30, 60, 5 * 60, 15 * 60]  # seconds, for the 5th, 6th, 7th and later failures
RESET_AFTER = 24 * 60 * 60  # a quiet day forgets old failures
NOTIFY_EVERY = 60 * 60

_PREFIX = "login-guard:"


def _key(email: str) -> str:
    return _PREFIX + hashlib.sha256(email.strip().lower().encode()).hexdigest()


def delay_for(failures: int) -> int:
    if failures < THRESHOLD:
        return 0
    return DELAYS[min(failures - THRESHOLD, len(DELAYS) - 1)]


# ---------------------------------------------------------------- storage (Redis, else database)


def _load(key: str) -> dict:
    try:
        return cache.get(key) or {}
    except Exception as exc:
        logger.warning("Login guard: cache unavailable (%s), using the database", exc.__class__.__name__)
        from .models import LoginFailure

        row = LoginFailure.objects.filter(key=key).first()
        return row.state if row else {}


def _save(key: str, state: dict):
    try:
        cache.set(key, state, timeout=RESET_AFTER)
        return
    except Exception:
        from .models import LoginFailure

        LoginFailure.objects.update_or_create(key=key, defaults={"state": state})


def _delete(key: str):
    from .models import LoginFailure

    try:
        cache.delete(key)
    except Exception:
        pass
    LoginFailure.objects.filter(key=key).delete()


# ---------------------------------------------------------------- API


def retry_after(email: str) -> int:
    """Seconds this address must still wait before trying again (0 = may try now)."""
    state = _load(_key(email))
    if not state or time.time() - state.get("last", 0) > RESET_AFTER:
        return 0
    return max(0, int(state.get("blocked_until", 0) - time.time()))


def record_failure(email: str, user=None, request=None) -> int:
    """Count a failed attempt; returns the wait now required (seconds)."""
    key = _key(email)
    now = time.time()
    state = _load(key)
    if not state or now - state.get("last", 0) > RESET_AFTER:
        state = {}
    failures = state.get("failures", 0) + 1
    wait = delay_for(failures)
    state.update(failures=failures, last=now, blocked_until=now + wait if wait else 0)
    if wait and user is not None and now - state.get("notified_at", 0) > NOTIFY_EVERY:
        state["notified_at"] = now
        _notify(user, failures, request)
    _save(key, state)
    return wait


def clear(email: str):
    _delete(_key(email))


def _notify(user, failures, request):
    from apps.core.audit import get_client_ip, log_action
    from apps.core.models import AuditLog
    from apps.notifications.models import NotificationType
    from apps.notifications.services import notify

    try:
        notify(user, NotificationType.SYSTEM, message="login_failures", params={"count": failures}, link="/settings?tab=security")
        log_action(
            None, AuditLog.Action.SECURITY, user, request=request,
            description=N_("Sign-in slowed down after repeated failed attempts"),
            changes={"failures": failures, "ip": get_client_ip(request)},
        )
    except Exception:  # never let a notification problem break sign-in
        logger.exception("Could not notify %s about failed sign-ins", user.pk)
