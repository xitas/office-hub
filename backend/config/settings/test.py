"""Test settings: in-memory SQLite unless TEST_DATABASE_URL points at Postgres."""
from .base import *  # noqa: F401,F403
from .base import env

DATABASES = {"default": env.db("TEST_DATABASE_URL", default="sqlite://:memory:")}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
# Fixed, test-only key (never use outside tests).
FIELD_ENCRYPTION_KEYS = ["Q2FuYXJ5VGVzdEtleUZvckZpZWxkRW5jcnlwdGlvbjA="]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
REDIS_URL = ""  # ignore any REDIS_URL from .env
# Tests never need Redis: local cache, and Celery tasks run inline (eagerly) and raise errors.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "crm-tests"}}
CELERY_BROKER_URL = "memory://"
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
# Opt-in Redis integration tests (shared rate limits): set TEST_REDIS_URL, e.g. redis://localhost:6379/15
TEST_REDIS_URL = env("TEST_REDIS_URL", default="")
REST_FRAMEWORK = {**REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": {"login": "1000/min", "password_reset": "1000/min"}}  # noqa: F405
