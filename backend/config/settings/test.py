"""Test settings: in-memory SQLite unless TEST_DATABASE_URL points at Postgres."""
from .base import *  # noqa: F401,F403
from .base import env

DATABASES = {"default": env.db("TEST_DATABASE_URL", default="sqlite://:memory:")}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
REST_FRAMEWORK = {**REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": {"login": "1000/min", "password_reset": "1000/min"}}  # noqa: F405
