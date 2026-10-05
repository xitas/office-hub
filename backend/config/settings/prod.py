"""Production settings. Every security-relevant value must come from the environment."""
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False  # never configurable in production
SECRET_KEY = env("DJANGO_SECRET_KEY")  # required: no default

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("Set DJANGO_ALLOWED_HOSTS to the exact host names (no '*') in production.")

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
if not CORS_ALLOWED_ORIGINS:
    raise ImproperlyConfigured("Set CORS_ALLOWED_ORIGINS to the frontend origin(s), e.g. https://crm.example.com")
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=CORS_ALLOWED_ORIGINS)

if not env.list("FIELD_ENCRYPTION_KEYS", default=[]):
    raise ImproperlyConfigured("Set FIELD_ENCRYPTION_KEYS (needed to read 2FA secrets).")

# HTTPS
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # set by the TLS-terminating proxy
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 365)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)  # opt in once the domain is ready

# Cookies
REFRESH_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = True

# Headers
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
# The API serves JSON plus Django admin; nothing loads third-party code. Admin templates use a
# few inline style attributes, hence 'unsafe-inline' for styles only.
CONTENT_SECURITY_POLICY = env(
    "CONTENT_SECURITY_POLICY",
    default=(
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; "
        "base-uri 'self'; form-action 'self'"
    ),
)
PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(self), payment=(), usb=()"

# Swagger UI loads assets from a CDN (blocked by the CSP above); expose docs only when asked.
API_DOCS_ENABLED = env.bool("API_DOCS_ENABLED", default=False)
if not SECURE_HSTS_PRELOAD:
    # Preload list submission is hard to undo; it's a deliberate, per-domain decision (set SECURE_HSTS_PRELOAD=True).
    SILENCED_SYSTEM_CHECKS = ["security.W021"]
