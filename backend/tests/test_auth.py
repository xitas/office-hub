import pyotp
import pytest
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.core.models import AuditLog

from .conftest import PASSWORD

pytestmark = pytest.mark.django_db

LOGIN = "/api/v1/auth/login/"
VERIFY = "/api/v1/auth/login/verify-otp/"
REFRESH = "/api/v1/auth/refresh/"
LOGOUT = "/api/v1/auth/logout/"
ME = "/api/v1/auth/me/"


def test_login_success_sets_refresh_cookie(api, staff):
    res = api.post(LOGIN, {"email": "STAFF@test.com", "password": PASSWORD}, format="json")
    assert res.status_code == 200
    assert res.data["access"]
    assert res.data["user"]["email"] == staff.email
    assert "tasks.view" in res.data["user"]["permissions"]
    assert "refresh" not in res.data
    assert res.cookies[settings.REFRESH_COOKIE_NAME]["httponly"]
    assert AuditLog.objects.filter(actor=staff, action="login").exists()


def test_login_mobile_returns_refresh_in_body(api, staff):
    res = api.post(LOGIN, {"email": staff.email, "password": PASSWORD, "client": "mobile"}, format="json")
    assert res.status_code == 200
    assert res.data["refresh"]


def test_login_wrong_password_is_audited(api, staff):
    res = api.post(LOGIN, {"email": staff.email, "password": "nope"}, format="json")
    assert res.status_code == 401
    assert res.data["detail"] == "Invalid email or password."
    assert AuditLog.objects.filter(action="login_failed").exists()


def test_inactive_user_cannot_login(api, staff):
    staff.is_active = False
    staff.save()
    res = api.post(LOGIN, {"email": staff.email, "password": PASSWORD}, format="json")
    assert res.status_code == 401


def test_refresh_with_cookie_and_logout_blacklists(api, staff):
    api.post(LOGIN, {"email": staff.email, "password": PASSWORD}, format="json")
    res = api.post(REFRESH, {}, format="json")
    assert res.status_code == 200 and res.data["access"]

    old_cookie = api.cookies[settings.REFRESH_COOKIE_NAME].value
    assert api.post(LOGOUT, {}, format="json").status_code == 204

    api.cookies[settings.REFRESH_COOKIE_NAME] = old_cookie
    assert api.post(REFRESH, {}, format="json").status_code == 401


def test_refresh_without_session_is_not_an_error(api):
    # First visit / signed out: nothing to refresh, but not a 401 either.
    assert api.post(REFRESH, {}, format="json").status_code == 204


def test_me_requires_auth_and_patch_updates_preferences(api, client_for, staff):
    assert api.get(ME).status_code == 401
    c = client_for(staff)
    res = c.patch(ME, {"language": "ur", "theme": "dark", "role": "admin"}, format="json")
    assert res.status_code == 200
    staff.refresh_from_db()
    assert staff.language == "ur" and staff.theme == "dark"
    assert staff.role == "staff"  # read-only through /me


def _enable_2fa(client_for, user):
    c = client_for(user)
    setup = c.post("/api/v1/auth/2fa/setup/")
    assert setup.status_code == 200 and setup.data["qr_code"].startswith("data:image/png;base64,")
    code = pyotp.TOTP(setup.data["secret"]).now()
    res = c.post("/api/v1/auth/2fa/enable/", {"code": code}, format="json")
    assert res.status_code == 200
    assert len(res.data["backup_codes"]) == 10
    return setup.data["secret"], res.data["backup_codes"]


def test_2fa_login_flow_with_totp(api, client_for, staff):
    secret, _ = _enable_2fa(client_for, staff)
    res = api.post(LOGIN, {"email": staff.email, "password": PASSWORD}, format="json")
    assert res.status_code == 200
    assert res.data == {"otp_required": True, "otp_token": res.data["otp_token"]}

    bad = api.post(VERIFY, {"otp_token": res.data["otp_token"], "code": "000000"}, format="json")
    assert bad.status_code == 401

    ok = api.post(VERIFY, {"otp_token": res.data["otp_token"], "code": pyotp.TOTP(secret).now()}, format="json")
    assert ok.status_code == 200 and ok.data["access"]


def test_2fa_backup_code_is_single_use(api, client_for, staff):
    _, codes = _enable_2fa(client_for, staff)
    token = api.post(LOGIN, {"email": staff.email, "password": PASSWORD}, format="json").data["otp_token"]
    assert api.post(VERIFY, {"otp_token": token, "code": codes[0]}, format="json").status_code == 200

    token = api.post(LOGIN, {"email": staff.email, "password": PASSWORD}, format="json").data["otp_token"]
    assert api.post(VERIFY, {"otp_token": token, "code": codes[0]}, format="json").status_code == 401
    staff.refresh_from_db()
    assert len(staff.backup_codes) == 9


def test_tampered_otp_token_rejected(api, client_for, staff):
    _enable_2fa(client_for, staff)
    res = api.post(VERIFY, {"otp_token": "forged", "code": "123456"}, format="json")
    assert res.status_code == 401


def test_2fa_disable_requires_password(client_for, staff):
    _enable_2fa(client_for, staff)
    c = client_for(staff)
    assert c.post("/api/v1/auth/2fa/disable/", {"password": "wrong"}, format="json").status_code == 400
    assert c.post("/api/v1/auth/2fa/disable/", {"password": PASSWORD}, format="json").status_code == 204
    staff.refresh_from_db()
    assert not staff.two_factor_enabled and staff.totp_secret == ""


def test_password_reset_flow(api, staff):
    assert api.post("/api/v1/auth/password/reset/", {"email": staff.email}, format="json").status_code == 204
    assert len(mail.outbox) == 1 and "reset-password?uid=" in mail.outbox[0].body
    # Unknown email: same response, no email.
    assert api.post("/api/v1/auth/password/reset/", {"email": "nobody@test.com"}, format="json").status_code == 204
    assert len(mail.outbox) == 1

    uid = urlsafe_base64_encode(force_bytes(staff.pk))
    token = default_token_generator.make_token(staff)
    res = api.post(
        "/api/v1/auth/password/reset/confirm/",
        {"uid": uid, "token": token, "new_password": "An0ther!Secret"},
        format="json",
    )
    assert res.status_code == 204
    staff.refresh_from_db()
    assert staff.check_password("An0ther!Secret")
    # Token can't be reused once the password changed.
    res = api.post(
        "/api/v1/auth/password/reset/confirm/",
        {"uid": uid, "token": token, "new_password": "Yet4nother!One"},
        format="json",
    )
    assert res.status_code == 400


def test_change_password(client_for, staff):
    c = client_for(staff)
    res = c.post(
        "/api/v1/auth/password/change/", {"current_password": "bad", "new_password": "N3w!Password"}, format="json"
    )
    assert res.status_code == 400
    res = c.post(
        "/api/v1/auth/password/change/", {"current_password": PASSWORD, "new_password": "N3w!Password"}, format="json"
    )
    assert res.status_code == 204
