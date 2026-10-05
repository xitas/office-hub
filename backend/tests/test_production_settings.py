"""Production settings pass Django's deploy checklist and refuse unsafe configuration."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from django.test import override_settings

BACKEND = Path(__file__).resolve().parent.parent
PROD_ENV = {
    "DJANGO_SETTINGS_MODULE": "config.settings.prod",
    "DJANGO_SECRET_KEY": "prod-test-" + "k" * 60,
    "DJANGO_ALLOWED_HOSTS": "crm.example.com",
    "CORS_ALLOWED_ORIGINS": "https://crm.example.com",
    "FIELD_ENCRYPTION_KEYS": Fernet.generate_key().decode(),
    "DATABASE_URL": "sqlite:///:memory:",
    "REDIS_URL": "",
}


def _manage(*args, **env_overrides):
    env = {**os.environ, **PROD_ENV, **env_overrides}
    return subprocess.run(
        [sys.executable, "manage.py", *args], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120
    )


def test_prod_settings_pass_deploy_checklist():
    result = _manage("check", "--deploy", "--fail-level", "WARNING")
    assert result.returncode == 0, result.stdout + result.stderr


def test_prod_settings_print_safe_values():
    code = (
        "from django.conf import settings as s;"
        "print(s.DEBUG, s.ALLOWED_HOSTS, s.SECURE_HSTS_SECONDS, s.SECURE_REFERRER_POLICY, s.API_DOCS_ENABLED,"
        " 'default-src' in s.CONTENT_SECURITY_POLICY)"
    )
    result = _manage("shell", "-c", code, DJANGO_DEBUG="True")  # DEBUG in env is ignored in production
    assert result.stdout.strip().splitlines()[-1] == (
        "False ['crm.example.com'] 31536000 strict-origin-when-cross-origin False True"
    ), result.stderr


@pytest.mark.parametrize(
    "override,message",
    [
        ({"DJANGO_ALLOWED_HOSTS": "*"}, "DJANGO_ALLOWED_HOSTS"),
        ({"DJANGO_ALLOWED_HOSTS": ""}, "DJANGO_ALLOWED_HOSTS"),
        ({"CORS_ALLOWED_ORIGINS": ""}, "CORS_ALLOWED_ORIGINS"),
        ({"FIELD_ENCRYPTION_KEYS": ""}, "FIELD_ENCRYPTION_KEYS"),
    ],
)
def test_prod_settings_refuse_unsafe_config(override, message):
    result = _manage("check", **override)
    assert result.returncode != 0 and message in result.stderr


@pytest.mark.django_db
def test_security_headers_middleware(client):
    with override_settings(CONTENT_SECURITY_POLICY="default-src 'self'", PERMISSIONS_POLICY="camera=()"):
        res = client.get("/api/v1/health/")
    assert res["Content-Security-Policy"] == "default-src 'self'"
    assert res["Permissions-Policy"] == "camera=()"
    assert res["X-Content-Type-Options"] == "nosniff"
    assert res["X-Frame-Options"] == "DENY"
