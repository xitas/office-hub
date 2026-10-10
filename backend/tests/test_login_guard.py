import time
from unittest import mock

import pytest
from django.core import mail
from django.core.cache import cache

from apps.accounts import login_guard
from apps.accounts.models import LoginFailure
from apps.core.models import AuditLog
from apps.notifications.models import Notification

from .conftest import PASSWORD

pytestmark = pytest.mark.django_db

LOGIN = "/api/v1/auth/login/"


def attempt(api, email, password="wrong-password"):
    return api.post(LOGIN, {"email": email, "password": password, "client": "mobile"}, format="json")


class Clock:
    """Moves login_guard's time forward without sleeping."""

    def __init__(self):
        self.now = time.time()

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(login_guard.time, "time", c)
    return c


def test_delays_grow_and_are_capped():
    assert [login_guard.delay_for(n) for n in range(1, 11)] == [0, 0, 0, 0, 30, 60, 300, 900, 900, 900]


def test_five_failures_slow_the_account_down(api, staff, clock):
    for _ in range(4):
        assert attempt(api, staff.email).status_code == 401
    assert attempt(api, staff.email).status_code == 401  # 5th failure: now 30 s to wait
    res = attempt(api, staff.email, PASSWORD)  # even the right password must wait
    assert res.status_code == 429 and 0 < int(res["Retry-After"]) <= 30
    assert "Too many failed sign-in attempts" in res.data["detail"]

    clock.now += 31
    assert attempt(api, staff.email).status_code == 401  # 6th failure: 1 minute
    clock.now += 31
    assert attempt(api, staff.email, PASSWORD).status_code == 429
    clock.now += 30
    assert attempt(api, staff.email, PASSWORD).status_code == 200  # never locked for good


def test_wait_is_capped_at_15_minutes(api, staff, clock):
    for _ in range(12):
        attempt(api, staff.email)
        clock.now += 16 * 60
    attempt(api, staff.email)
    assert login_guard.retry_after(staff.email) == 15 * 60


def test_success_clears_the_count(api, staff):
    for _ in range(4):
        attempt(api, staff.email)
    assert attempt(api, staff.email, PASSWORD).status_code == 200
    for _ in range(4):
        assert attempt(api, staff.email).status_code == 401  # counting starts again


def test_password_reset_clears_the_count(api, staff):
    from django.contrib.auth.tokens import default_token_generator
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode

    for _ in range(5):
        attempt(api, staff.email)
    assert login_guard.retry_after(staff.email) > 0
    res = api.post("/api/v1/auth/password/reset/confirm/", {
        "uid": urlsafe_base64_encode(force_bytes(staff.pk)),
        "token": default_token_generator.make_token(staff),
        "new_password": "An0ther!Strong#Pass",
    }, format="json")
    assert res.status_code == 204
    assert login_guard.retry_after(staff.email) == 0


def test_unknown_email_gets_the_same_answers(api, staff):
    real = [attempt(api, staff.email) for _ in range(6)]
    fake = [attempt(api, "nobody@test.com") for _ in range(6)]
    assert [r.status_code for r in real] == [r.status_code for r in fake] == [401] * 5 + [429]
    assert real[0].data == fake[0].data
    assert real[-1].data["detail"] == fake[-1].data["detail"]


def test_counts_are_per_account_and_ignore_case(api, staff, admin):
    for _ in range(5):
        attempt(api, staff.email.upper())
    assert attempt(api, staff.email, PASSWORD).status_code == 429
    assert attempt(api, admin.email, PASSWORD).status_code == 200


def test_owner_is_notified_at_most_hourly(api, staff, clock, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        for _ in range(5):
            attempt(api, staff.email)
    notes = Notification.objects.filter(recipient=staff, message_key="login_failures")
    assert notes.count() == 1
    assert len(mail.outbox) == 1 and staff.email in mail.outbox[0].to
    assert AuditLog.objects.filter(action=AuditLog.Action.SECURITY, object_id=str(staff.pk)).exists()

    for _ in range(3):  # more failures within the hour: no new notice
        clock.now += 16 * 60
        attempt(api, staff.email)
    assert notes.count() == 1
    clock.now += 61 * 60
    attempt(api, staff.email)
    assert notes.count() == 2


def test_notification_follows_reader_language(client_for, api, staff):
    for _ in range(5):
        attempt(api, staff.email)
    res = client_for(staff).get("/api/v1/notifications/", HTTP_ACCEPT_LANGUAGE="ur")
    assert res.data["results"][0]["title"] == "آپ کے اکاؤنٹ میں سائن اِن کی ناکام کوششیں"


def test_failed_2fa_codes_count_too(api, staff, clock):
    from apps.accounts import twofactor

    staff.two_factor_enabled = True
    staff.save()
    with mock.patch.object(twofactor, "verify_second_factor", return_value=False):
        for _ in range(5):
            token = attempt(api, staff.email, PASSWORD).data["otp_token"]
            res = api.post("/api/v1/auth/login/verify-otp/", {"otp_token": token, "code": "000000"}, format="json")
            assert res.status_code == 401
    res = attempt(api, staff.email, PASSWORD)
    assert res.status_code == 429


def test_falls_back_to_the_database_without_redis(api, staff):
    broken = mock.patch.object(cache, "get", side_effect=ConnectionError("redis down"))
    broken_set = mock.patch.object(cache, "set", side_effect=ConnectionError("redis down"))
    with broken, broken_set:
        for _ in range(5):
            assert attempt(api, staff.email).status_code == 401  # no server error
        assert LoginFailure.objects.count() == 1
        assert attempt(api, staff.email, PASSWORD).status_code == 429
    with broken, broken_set, mock.patch.object(cache, "delete", side_effect=ConnectionError("redis down")):
        login_guard.clear(staff.email)
    assert not LoginFailure.objects.exists()


def test_login_works_while_redis_is_down(api, staff):
    """The per-IP limit and permission checks fall back to an in-process cache instead of failing."""
    with mock.patch.object(cache, "get", side_effect=ConnectionError), mock.patch.object(
        cache, "set", side_effect=ConnectionError
    ), mock.patch.object(cache, "delete", side_effect=ConnectionError), mock.patch.object(
        cache, "add", side_effect=ConnectionError
    ):
        res = attempt(api, staff.email, PASSWORD)
        assert res.status_code == 200
        me = api.get("/api/v1/auth/me/", HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")
        assert me.status_code == 200
