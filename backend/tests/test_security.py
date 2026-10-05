"""Security hardening: encrypted 2FA secrets, avatar sanitising, rate limiting, WebSocket tickets, CSRF."""
import io

import pyotp
import pytest
from channels.testing import WebsocketCommunicator
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from PIL import Image
from rest_framework.throttling import ScopedRateThrottle

from apps.accounts.models import User
from apps.core import fields
from apps.core.audit import get_client_ip
from apps.core.ws_auth import TICKET_TTL, issue_ticket, redeem_ticket
from config.asgi import application

from .conftest import PASSWORD

LOGIN = "/api/v1/auth/login/"
VERIFY = "/api/v1/auth/login/verify-otp/"


# ---------------------------------------------------------------- 2FA secret encryption


def _raw_secret(user):
    with connection.cursor() as c:
        c.execute("SELECT totp_secret FROM accounts_user WHERE id = %s", [user.pk])
        return c.fetchone()[0]


@pytest.mark.django_db
def test_totp_secret_is_encrypted_at_rest(staff):
    secret = pyotp.random_base32()
    staff.totp_secret = secret
    staff.save()
    raw = _raw_secret(staff)
    assert raw.startswith(fields.PREFIX) and secret not in raw
    staff.refresh_from_db()
    assert staff.totp_secret == secret


@pytest.mark.django_db
def test_two_factor_login_works_with_encrypted_secret(api, client_for, staff):
    setup = client_for(staff).post("/api/v1/auth/2fa/setup/").data
    client_for(staff).post("/api/v1/auth/2fa/enable/", {"code": pyotp.TOTP(setup["secret"]).now()}, format="json")
    assert fields.is_encrypted(_raw_secret(staff))

    token = api.post(LOGIN, {"email": staff.email, "password": PASSWORD}, format="json").data["otp_token"]
    res = api.post(VERIFY, {"otp_token": token, "code": pyotp.TOTP(setup["secret"]).now()}, format="json")
    assert res.status_code == 200 and res.data["access"]


def test_key_rotation_old_key_still_decrypts(settings):
    from cryptography.fernet import Fernet

    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    settings.FIELD_ENCRYPTION_KEYS = [old]
    stored = fields.encrypt("JBSWY3DPEHPK3PXP")
    settings.FIELD_ENCRYPTION_KEYS = [new, old]  # rotated: new key first, old kept for reading
    assert fields.decrypt(stored) == "JBSWY3DPEHPK3PXP"
    settings.FIELD_ENCRYPTION_KEYS = [new]  # old key removed too early
    with pytest.raises(Exception, match="FIELD_ENCRYPTION_KEYS"):
        fields.decrypt(stored)


def test_missing_key_fails_loudly(settings):
    settings.FIELD_ENCRYPTION_KEYS = []
    with pytest.raises(Exception, match="FIELD_ENCRYPTION_KEYS is not set"):
        fields.encrypt("x")


@pytest.mark.django_db(transaction=True)
def test_data_migration_encrypts_existing_plaintext_secrets():
    executor = MigrationExecutor(connection)
    executor.migrate([("accounts", "0002_alter_department_options_alter_user_options")])
    old_apps = executor.loader.project_state([("accounts", "0002_alter_department_options_alter_user_options")]).apps
    OldUser = old_apps.get_model("accounts", "User")
    legacy_secret = pyotp.random_base32()
    OldUser.objects.create(email="legacy@test.com", full_name="Legacy", password="x", totp_secret=legacy_secret, two_factor_enabled=True)

    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(executor.loader.graph.leaf_nodes())

    user = User.objects.get(email="legacy@test.com")
    raw = _raw_secret(user)
    assert fields.is_encrypted(raw) and legacy_secret not in raw
    assert user.totp_secret == legacy_secret  # transparently decrypted
    assert pyotp.TOTP(user.totp_secret).verify(pyotp.TOTP(legacy_secret).now())


# ---------------------------------------------------------------- avatar uploads


def _image(fmt="PNG", size=(64, 64), exif=None, mode="RGB"):
    buf = io.BytesIO()
    img = Image.new(mode, size, color=(200, 30, 30))
    kwargs = {"exif": exif} if exif is not None else {}
    img.save(buf, fmt, **kwargs)
    return buf.getvalue()


def _upload(client, content, name="photo.png", content_type="image/png"):
    return client.patch(
        "/api/v1/auth/me/", {"avatar": SimpleUploadedFile(name, content, content_type=content_type)}, format="multipart"
    )


@pytest.fixture
def media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


@pytest.mark.django_db
def test_avatar_valid_png_is_accepted_and_renamed(client_for, staff, media_root):
    res = _upload(client_for(staff), _image("PNG"), name="../../evil.png")
    assert res.status_code == 200
    staff.refresh_from_db()
    assert staff.avatar.name.startswith("avatars/") and "evil" not in staff.avatar.name


@pytest.mark.django_db
def test_avatar_rejects_oversized_file(client_for, staff, media_root):
    big = _image("PNG") + b"\0" * (2 * 1024 * 1024)
    res = _upload(client_for(staff), big)
    assert res.status_code == 400 and "2 MB" in res.data["errors"]["avatar"][0]


@pytest.mark.django_db
def test_avatar_rejects_non_image_with_image_extension(client_for, staff, media_root):
    res = _upload(client_for(staff), b"<script>alert(1)</script>", name="x.png")
    assert res.status_code == 400


@pytest.mark.django_db
def test_avatar_rejects_disallowed_format(client_for, staff, media_root):
    res = _upload(client_for(staff), _image("GIF"), name="x.gif", content_type="image/gif")
    assert res.status_code == 400 and "JPEG, PNG or WebP" in res.data["errors"]["avatar"][0]


@pytest.mark.django_db
def test_avatar_strips_exif_and_resizes(client_for, staff, media_root):
    exif = Image.Exif()
    exif[0x8825] = {1: "N", 2: (24.0, 51.0, 0.0)}  # GPSInfo: latitude
    exif[0x010F] = "PhoneMaker"
    content = _image("JPEG", size=(3000, 2000), exif=exif.tobytes())
    assert Image.open(io.BytesIO(content)).getexif()  # precondition: EXIF present

    res = _upload(client_for(staff), content, name="trip.jpg", content_type="image/jpeg")
    assert res.status_code == 200
    staff.refresh_from_db()
    with staff.avatar.open("rb") as f:
        stored = Image.open(f)
        stored.load()
    assert stored.format == "JPEG"
    assert max(stored.size) == 512 and stored.size == (512, 341)
    assert not stored.getexif()  # GPS and camera metadata gone


@pytest.mark.django_db
def test_avatar_webp_accepted_and_old_file_deleted(client_for, staff, media_root):
    c = client_for(staff)
    _upload(c, _image("PNG"))
    staff.refresh_from_db()
    first = media_root / staff.avatar.name
    assert first.exists()
    assert _upload(c, _image("WEBP"), name="p.webp", content_type="image/webp").status_code == 200
    staff.refresh_from_db()
    assert staff.avatar.name.endswith(".webp") and not first.exists()


# ---------------------------------------------------------------- rate limiting


@pytest.fixture
def strict_login_limit(monkeypatch):
    monkeypatch.setitem(ScopedRateThrottle.THROTTLE_RATES, "login", "3/min")
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_login_rate_limit_cannot_be_bypassed_with_forwarded_header(api, staff, strict_login_limit):
    codes = [
        api.post(
            LOGIN, {"email": staff.email, "password": "wrong"}, format="json", HTTP_X_FORWARDED_FOR=f"10.0.0.{i}"
        ).status_code
        for i in range(5)
    ]
    assert codes[:3] == [401, 401, 401]
    assert codes[3:] == [429, 429]  # rotating X-Forwarded-For doesn't reset the counter


def test_client_ip_trusts_forwarded_header_only_behind_configured_proxies(rf, settings):
    from rest_framework.settings import api_settings

    req = rf.get("/", HTTP_X_FORWARDED_FOR="6.6.6.6, 10.0.0.9", REMOTE_ADDR="127.0.0.1")
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 0}
    api_settings.reload()
    assert get_client_ip(req) == "127.0.0.1"
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}
    api_settings.reload()
    assert get_client_ip(req) == "10.0.0.9"  # the address our one proxy saw, not the client's claim


def test_cache_config_uses_redis_when_configured():
    from config.settings.services import cache_config

    assert cache_config("redis://r:6379/0")["default"]["BACKEND"].endswith("RedisCache")
    assert cache_config("")["default"]["BACKEND"].endswith("LocMemCache")


@pytest.mark.django_db
def test_rate_limit_is_shared_across_processes_via_redis(api, staff, settings, monkeypatch):
    """Two 'processes' (separate cache connections) share one counter in Redis."""
    redis_url = settings.TEST_REDIS_URL
    if not redis_url:
        pytest.skip("set TEST_REDIS_URL to run Redis integration tests")
    from django.core.cache.backends.redis import RedisCache

    monkeypatch.setitem(ScopedRateThrottle.THROTTLE_RATES, "login", "3/min")
    process_a = RedisCache(redis_url, {"KEY_PREFIX": "crm-test"})
    process_b = RedisCache(redis_url, {"KEY_PREFIX": "crm-test"})
    process_a.clear()
    try:
        monkeypatch.setattr(ScopedRateThrottle, "cache", process_a)
        for _ in range(3):
            assert api.post(LOGIN, {"email": staff.email, "password": "x"}, format="json").status_code == 401
        monkeypatch.setattr(ScopedRateThrottle, "cache", process_b)  # request lands on another server process
        assert api.post(LOGIN, {"email": staff.email, "password": "x"}, format="json").status_code == 429
    finally:
        process_a.clear()


# ---------------------------------------------------------------- WebSocket tickets


@pytest.mark.django_db
def test_ws_ticket_requires_auth_and_is_single_use(api, client_for, staff):
    assert api.post("/api/v1/auth/ws-ticket/").status_code == 401
    res = client_for(staff).post("/api/v1/auth/ws-ticket/")
    assert res.status_code == 200 and res.data["expires_in"] == TICKET_TTL
    ticket = res.data["ticket"]
    assert redeem_ticket(ticket) == staff.pk
    assert redeem_ticket(ticket) is None  # second use fails
    assert redeem_ticket("forged") is None


@pytest.mark.django_db
def test_ws_ticket_expires(staff, monkeypatch):
    ticket = issue_ticket(staff)
    cache.delete(f"ws-ticket:{__import__('hashlib').sha256(ticket.encode()).hexdigest()}")  # simulate TTL expiry
    assert redeem_ticket(ticket) is None


@pytest.mark.django_db(transaction=True)
async def test_websocket_rejects_jwt_in_url_and_reused_ticket(staff):
    from rest_framework_simplejwt.tokens import AccessToken

    headers = [(b"origin", b"http://localhost")]
    jwt_in_url = WebsocketCommunicator(application, f"/ws/notifications/?token={AccessToken.for_user(staff)}", headers=headers)
    assert (await jwt_in_url.connect())[0] is False  # the old URL-token method no longer works

    ticket = issue_ticket(staff)
    first = WebsocketCommunicator(application, f"/ws/notifications/?ticket={ticket}", headers=headers)
    assert (await first.connect())[0] is True
    await first.disconnect()
    replay = WebsocketCommunicator(application, f"/ws/notifications/?ticket={ticket}", headers=headers)
    assert (await replay.connect())[0] is False


@pytest.mark.django_db(transaction=True)
async def test_websocket_rejects_foreign_origin(staff):
    ws = WebsocketCommunicator(
        application, f"/ws/notifications/?ticket={issue_ticket(staff)}", headers=[(b"origin", b"https://evil.example")]
    )
    assert (await ws.connect())[0] is False


# ---------------------------------------------------------------- refresh-cookie CSRF


@pytest.mark.django_db
def test_cookie_refresh_requires_app_header_and_own_origin(api, staff):
    api.post(LOGIN, {"email": staff.email, "password": PASSWORD}, format="json")
    assert api.post("/api/v1/auth/refresh/", {}, format="json").status_code == 403  # e.g. a cross-site form post
    assert (
        api.post(
            "/api/v1/auth/refresh/", {}, format="json", HTTP_X_REQUESTED_WITH="XMLHttpRequest", HTTP_ORIGIN="https://evil.example"
        ).status_code
        == 403
    )
    ok = api.post(
        "/api/v1/auth/refresh/", {}, format="json", HTTP_X_REQUESTED_WITH="XMLHttpRequest", HTTP_ORIGIN="http://localhost:5173"
    )
    assert ok.status_code == 200
    assert api.post("/api/v1/auth/logout/", {}, format="json").status_code == 403


@pytest.mark.django_db
def test_mobile_body_token_refresh_needs_no_header(api, staff):
    refresh = api.post(LOGIN, {"email": staff.email, "password": PASSWORD, "client": "mobile"}, format="json").data["refresh"]
    api.cookies.clear()
    assert api.post("/api/v1/auth/refresh/", {"refresh": refresh}, format="json").status_code == 200
