"""Health checks for the database, Redis, Celery workers and Celery Beat."""
import time

from django.conf import settings
from django.core.cache import cache
from django.db import connection

from .tasks import HEARTBEAT_CACHE_KEY

HEARTBEAT_STALE_AFTER = 180  # seconds; Beat schedules the heartbeat every 60s


def check_database() -> dict:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return {"ok": True, "vendor": connection.vendor}
    except Exception as exc:  # report, don't raise: this is a status page
        return {"ok": False, "error": exc.__class__.__name__}


def check_redis() -> dict:
    if not settings.REDIS_URL:
        return {"ok": None, "configured": False, "detail": "REDIS_URL not set (in-process fallbacks in use)"}
    try:
        import redis

        client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=1)
        started = time.perf_counter()
        client.ping()
        return {"ok": True, "configured": True, "latency_ms": round((time.perf_counter() - started) * 1000, 1)}
    except Exception as exc:
        return {"ok": False, "configured": True, "error": exc.__class__.__name__}


def check_celery_workers() -> dict:
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        return {"ok": None, "mode": "eager", "detail": "No broker: tasks run inline in the web process"}
    try:
        from config.celery import app

        replies = app.control.ping(timeout=1.0) or []
        workers = sorted(name for reply in replies for name in reply)
        return {"ok": bool(workers), "mode": "worker", "workers": workers}
    except Exception as exc:
        return {"ok": False, "mode": "worker", "error": exc.__class__.__name__}


def check_beat() -> dict:
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        return {"ok": None, "detail": "Scheduler not used without a broker"}
    last = cache.get(HEARTBEAT_CACHE_KEY)
    if last is None:
        return {"ok": False, "last_heartbeat_seconds_ago": None}
    age = round(time.time() - last)
    return {"ok": age <= HEARTBEAT_STALE_AFTER, "last_heartbeat_seconds_ago": age}


def check_channels(redis: dict) -> dict:
    backend = settings.CHANNEL_LAYERS["default"]["BACKEND"].rsplit(".", 1)[-1]
    if backend == "RedisChannelLayer":
        return {"ok": bool(redis.get("ok")), "backend": backend}
    return {"ok": None, "backend": backend, "detail": "In-process layer: live updates only within one server process"}


def full_report() -> dict:
    redis = check_redis()
    checks = {
        "database": check_database(),
        "redis": redis,
        "celery_workers": check_celery_workers(),
        "celery_beat": check_beat(),
        "channels": check_channels(redis),
    }
    # ok: True = healthy, False = failing, None = not applicable in this setup.
    status = "ok" if all(c.get("ok") is not False for c in checks.values()) else "degraded"
    return {"status": status, "checks": checks}
