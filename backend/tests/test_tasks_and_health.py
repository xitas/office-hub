"""Celery tasks (run eagerly in tests — no Redis needed) and the health endpoints."""
import smtplib
import time
from unittest import mock

import pytest
from django.core import mail
from django.core.cache import cache

from apps.core import health
from apps.core.email import queue_email
from apps.core.tasks import HEARTBEAT_CACHE_KEY, heartbeat, send_email
from apps.notifications.services import notify


@pytest.mark.django_db
def test_notification_email_is_sent_by_celery_task_after_commit(manager, staff, django_capture_on_commit_callbacks):
    with mock.patch("apps.core.email.send_email.delay", wraps=send_email.delay) as delay:
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            notify(staff, "task_assigned", "Quarterly report", body="Due Friday", actor=manager)
            assert len(mail.outbox) == 0  # nothing sent inside the request/transaction
            delay.assert_not_called()
        assert len(callbacks) == 1
        callbacks[0]()  # transaction commits -> task enqueued (runs inline in tests)
    delay.assert_called_once()
    subject, body, recipients = delay.call_args.args
    assert subject == "Quarterly report" and recipients == [staff.email] and "Due Friday" in body
    assert len(mail.outbox) == 1 and mail.outbox[0].to == [staff.email]


@pytest.mark.django_db
def test_rolled_back_transaction_sends_no_email(staff, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        queue_email("Subject", "Body", [staff.email])
    # Callbacks are discarded when the transaction rolls back; none ran.
    assert len(callbacks) == 1 and len(mail.outbox) == 0


def test_send_email_task_schedules_retry_on_smtp_failure():
    from celery.exceptions import Retry

    with mock.patch("apps.core.tasks.send_mail", side_effect=smtplib.SMTPServerDisconnected("connection lost")):
        with pytest.raises(Retry) as info:  # in a worker this re-queues the task with backoff
            send_email.apply(args=("S", "B", ["a@test.com"]), throw=True)
    assert isinstance(info.value.exc, smtplib.SMTPServerDisconnected)
    assert info.value.when > 0  # delayed retry (exponential backoff with jitter)


def test_send_email_task_sends(settings):
    result = send_email.apply(args=("Hello", "Body", ["a@test.com"]))
    assert result.successful() and result.result == 1
    assert mail.outbox[-1].subject == "Hello"


def test_send_email_task_retry_policy():
    assert send_email.max_retries == 5
    assert smtplib.SMTPException in send_email.autoretry_for


def test_tasks_run_inline_without_broker(settings):
    assert settings.CELERY_TASK_ALWAYS_EAGER is True
    assert settings.CELERY_BROKER_URL == "memory://"


def test_celery_config_switches_to_redis_broker():
    from config.settings.services import celery_config, channel_layers_config

    assert celery_config("redis://r:6379/0") == {
        "CELERY_BROKER_URL": "redis://r:6379/0",
        "CELERY_TASK_ALWAYS_EAGER": False,
        "CELERY_TASK_EAGER_PROPAGATES": False,
    }
    assert celery_config("")["CELERY_TASK_ALWAYS_EAGER"] is True
    assert channel_layers_config("redis://r:6379/0")["default"]["BACKEND"] == "channels_redis.core.RedisChannelLayer"


@pytest.mark.django_db
def test_heartbeat_schedule_is_stored_in_database():
    from django_celery_beat.models import PeriodicTask

    task = PeriodicTask.objects.get(name="System heartbeat")
    assert task.task == "apps.core.tasks.heartbeat" and task.enabled
    assert (task.interval.every, task.interval.period) == (1, "minutes")


# ---------------------------------------------------------------- health


@pytest.mark.django_db
def test_liveness_is_public(api):
    res = api.get("/api/v1/health/")
    assert res.status_code == 200 and res.data == {"status": "ok"}


@pytest.mark.django_db
def test_system_health_admin_only_and_reports_eager_mode(client_for, admin, staff, manager):
    assert client_for(staff).get("/api/v1/system/health/").status_code == 403
    assert client_for(manager).get("/api/v1/system/health/").status_code == 403
    data = client_for(admin).get("/api/v1/system/health/").data
    assert data["status"] == "ok"
    assert data["checks"]["database"]["ok"] is True
    assert data["checks"]["celery_workers"]["mode"] == "eager"
    assert data["checks"]["redis"]["configured"] is False


def test_beat_health_uses_heartbeat_age(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = False
    cache.delete(HEARTBEAT_CACHE_KEY)
    assert health.check_beat()["ok"] is False
    heartbeat.apply()
    assert health.check_beat() == {"ok": True, "last_heartbeat_seconds_ago": 0}
    cache.set(HEARTBEAT_CACHE_KEY, time.time() - 600)
    assert health.check_beat()["ok"] is False  # stale: beat or worker stopped


def test_worker_health_with_broker(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = False
    with mock.patch("config.celery.app.control.ping", return_value=[{"celery@pc": {"ok": "pong"}}]):
        assert health.check_celery_workers() == {"ok": True, "mode": "worker", "workers": ["celery@pc"]}
    with mock.patch("config.celery.app.control.ping", return_value=[]):
        assert health.check_celery_workers()["ok"] is False


@pytest.mark.django_db
def test_degraded_status_when_redis_down(client_for, admin, settings):
    settings.REDIS_URL = "redis://127.0.0.1:1/0"  # nothing listens on port 1
    data = client_for(admin).get("/api/v1/system/health/").data
    assert data["checks"]["redis"]["ok"] is False and data["status"] == "degraded"


def test_channels_health_follows_layer_and_redis(settings):
    settings.CHANNEL_LAYERS = {"default": {"BACKEND": "channels_redis.core.RedisChannelLayer"}}
    assert health.check_channels({"ok": True}) == {"ok": True, "backend": "RedisChannelLayer"}
    assert health.check_channels({"ok": False})["ok"] is False
    settings.CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    assert health.check_channels({"ok": None})["ok"] is None
