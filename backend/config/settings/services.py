"""Redis-backed service configuration, with in-process fallbacks for local development.

With REDIS_URL set (production, and development with Docker), the cache (login
rate limits, WebSocket tickets, health heartbeats), the Channels layer and the
Celery broker all use Redis, so they work across every server/worker process.
Without it, each falls back to an in-process equivalent: fine for a single
`runserver`, but limits and live pushes are then per process.
"""


def cache_config(redis_url: str) -> dict:
    if redis_url:
        return {
            "default": {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": redis_url,
                "KEY_PREFIX": "crm",
                "TIMEOUT": 300,
            }
        }
    return {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "crm-local"}}


def channel_layers_config(redis_url: str) -> dict:
    if redis_url:
        return {
            "default": {
                "BACKEND": "channels_redis.core.RedisChannelLayer",
                "CONFIG": {"hosts": [redis_url], "prefix": "crm:channels"},
            }
        }
    return {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}


def celery_config(redis_url: str) -> dict:
    """Without a broker, tasks run inline (eagerly) in the calling process."""
    return {
        "CELERY_BROKER_URL": redis_url or "memory://",
        "CELERY_TASK_ALWAYS_EAGER": not redis_url,
        "CELERY_TASK_EAGER_PROPAGATES": not redis_url,
    }
