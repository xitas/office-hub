"""Reminders (due soon, overdue, assigned), the morning digest, no duplicates and catch-up after downtime."""
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from unittest import mock

import pytest
from django.core import mail

from apps.notifications.models import Notification, NotificationPreference
from apps.tasks import schedule
from apps.tasks.models import DigestLog, ReminderLog, Task
from apps.timeline.models import TimelineEntry

pytestmark = pytest.mark.django_db

TASKS = "/api/v1/tasks/"
DAY = date(2026, 10, 12)


def at_office(day, hour=10, minute=0):
    """Freeze "now" at a wall-clock time in Karachi (UTC+5)."""
    moment = datetime.combine(day, time(hour, minute), tzinfo=dt_timezone.utc) - timedelta(hours=5)
    return mock.patch("django.utils.timezone.now", return_value=moment)


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {"admin": admin, "manager": manager, "staff": staff, "colleague": make_user("colleague@test.com", full_name="Sara Colleague")}


def make(title, people_on, creator=None, **extra):
    task = Task.objects.create(title=title, created_by=creator or people_on[0], **extra)
    task.assignees.set(people_on)
    return task


def notes(user, kind):
    return Notification.objects.filter(recipient=user, type=kind)


# ================================================================ due soon


def test_due_soon_one_day_before(people):
    s = people["staff"]
    task = make("Send contract", [s], due_date=DAY + timedelta(days=1), due_time=time(10, 0))
    with at_office(DAY, 9, 59):
        assert schedule.send_due_soon() == 0
    with at_office(DAY, 10, 1):
        assert schedule.send_due_soon() == 1
        assert schedule.send_due_soon() == 0  # never twice
    note = notes(s, "task_deadline").get()
    assert note.message_key == "task_due_soon" and note.link == f"/tasks/{task.pk}"


def test_date_only_task_is_due_at_end_of_day(people):
    make("Report", [people["staff"]], due_date=DAY + timedelta(days=1))  # due by 23:59:59 tomorrow
    with at_office(DAY, 23, 58):
        assert schedule.send_due_soon() == 0
    with at_office(DAY + timedelta(days=1), 0, 1):
        assert schedule.send_due_soon() == 1


@pytest.mark.parametrize("lead,sends_at_8h_before,sends_at_30min_before", [("1d", True, False), ("1h", False, True), ("off", False, False)])
def test_reminder_lead_preference(people, lead, sends_at_8h_before, sends_at_30min_before):
    s = people["staff"]
    s.task_reminder_lead = lead
    s.save()
    make("Call client", [s], due_date=DAY, due_time=time(18, 0))
    with at_office(DAY, 10):
        assert schedule.send_due_soon() == int(sends_at_8h_before)
    with at_office(DAY, 17, 30):
        schedule.send_due_soon()
    assert notes(s, "task_deadline").exists() is (sends_at_8h_before or sends_at_30min_before)


def test_due_soon_is_not_sent_late(people):
    """After downtime, a reminder for a task that is already due would be noise: the overdue notice covers it."""
    make("Missed", [people["staff"]], due_date=DAY, due_time=time(9, 0))
    with at_office(DAY, 11):
        assert schedule.send_due_soon() == 0


def test_new_due_date_allows_a_new_reminder(people):
    s = people["staff"]
    task = make("Move me", [s], due_date=DAY, due_time=time(15, 0))
    with at_office(DAY, 14):
        assert schedule.send_due_soon() == 1
    task.due_date = DAY + timedelta(days=1)
    task.save()
    with at_office(DAY + timedelta(days=1), 14):
        assert schedule.send_due_soon() == 1
    assert ReminderLog.objects.count() == 2


def test_each_assignee_once_and_preferences_respected(people, django_capture_on_commit_callbacks):
    s, c = people["staff"], people["colleague"]
    NotificationPreference.objects.create(user=c, type="task_deadline", in_app=False, email=True)
    make("Team task", [s, c], due_date=DAY, due_time=time(16, 0))
    with at_office(DAY, 15), django_capture_on_commit_callbacks(execute=True):
        assert schedule.send_due_soon() == 2
    assert notes(s, "task_deadline").count() == 1
    assert not notes(c, "task_deadline").exists()  # in-app off for the colleague…
    assert [m.to for m in mail.outbox] == [[c.email]]  # …who asked for email instead


def test_done_tasks_get_no_reminders(people):
    make("Already done", [people["staff"]], due_date=DAY, due_time=time(15, 0), status="done")
    with at_office(DAY, 14):
        assert schedule.send_due_soon() == 0
    with at_office(DAY, 16):
        assert schedule.send_overdue() == 0


# ================================================================ overdue


def test_overdue_once(people):
    s = people["staff"]
    make("Late", [s], due_date=DAY, due_time=time(12, 0))
    with at_office(DAY, 11, 59):
        assert schedule.send_overdue() == 0
    with at_office(DAY, 12, 5):
        assert schedule.send_overdue() == 1
    with at_office(DAY, 18):
        assert schedule.send_overdue() == 0
    assert notes(s, "task_overdue").get().message_key == "task_overdue"


def test_overdue_catch_up_is_limited(people):
    """After the worker was down for a week, only recently overdue tasks are announced (no flood)."""
    s = people["staff"]
    make("Overdue yesterday", [s], due_date=DAY - timedelta(days=1))
    for n in range(3, 8):
        make(f"Old {n}", [s], due_date=DAY - timedelta(days=n))
    with at_office(DAY, 10):
        assert schedule.send_overdue() == 1
    assert [n.params["task"] for n in notes(s, "task_overdue")] == ["Overdue yesterday"]


# ================================================================ assigned to you


def test_assigned_notifications(client_for, people):
    c = client_for(people["staff"])
    res = c.post(TASKS, {"title": "Shared", "assignees": [people["staff"].pk, people["colleague"].pk]}, format="json")
    assert notes(people["colleague"], "task_assigned").count() == 1
    assert not notes(people["staff"], "task_assigned").exists()  # assigning yourself: no notice
    c.patch(f"{TASKS}{res.data['id']}/", {"title": "Shared v2"}, format="json")
    m = client_for(people["manager"])
    m.patch(f"{TASKS}{res.data['id']}/", {"assignees": [people["staff"].pk, people["colleague"].pk, people["manager"].pk]}, format="json")
    assert notes(people["colleague"], "task_assigned").count() == 1  # not again
    m.patch(f"{TASKS}{res.data['id']}/", {"assignees": [people["staff"].pk]}, format="json")
    m.patch(f"{TASKS}{res.data['id']}/", {"assignees": [people["staff"].pk, people["colleague"].pk]}, format="json")
    assert notes(people["colleague"], "task_assigned").count() == 2  # re-added: told again
    note = notes(people["colleague"], "task_assigned").first()
    assert note.message_key == "task_assigned" and note.params["actor"]


# ================================================================ morning digest


@pytest.fixture
def digest_data(people):
    s = people["staff"]
    make("Today call", [s], due_date=DAY, due_time=time(11, 0))
    make("Late report", [s], due_date=DAY - timedelta(days=3))
    make("Next week", [s], due_date=DAY + timedelta(days=7))
    make("Finished", [s], due_date=DAY, status="done")
    from apps.contacts.models import Contact

    ali = Contact.objects.create(first_name="Ali", last_name="Khan", assigned_to=s)
    TimelineEntry.objects.create(kind="note", contact=ali, summary="Ask about the order\nmore", follow_up_on=DAY, created_by=s)
    TimelineEntry.objects.create(kind="note", contact=ali, summary="Old", follow_up_on=DAY - timedelta(days=30), created_by=s)
    return s


def test_digest_content(people, digest_data, django_capture_on_commit_callbacks):
    with at_office(DAY, 9, 5), django_capture_on_commit_callbacks(execute=True):
        assert schedule.send_digests() == 1
    msg = mail.outbox[0]
    assert msg.to == [digest_data.email]
    assert msg.subject == "Your day: 1 task due today, 1 overdue, 1 client follow-up"
    assert "Today call 11:00" in msg.body and "Late report (09/10/2026)" in msg.body
    assert "Next week" not in msg.body and "Finished" not in msg.body
    assert "Ali Khan: Ask about the order (12/10/2026)" in msg.body and "Old" not in msg.body
    assert "/tasks/" in msg.body and "/contacts/" in msg.body


def test_digest_moves_tasks_whose_time_has_passed_to_overdue(people, digest_data, django_capture_on_commit_callbacks):
    make("Early meeting", [digest_data], due_date=DAY, due_time=time(8, 30))
    make("All-day item", [digest_data], due_date=DAY)  # no time: due until the end of the day
    with at_office(DAY, 9, 5), django_capture_on_commit_callbacks(execute=True):
        assert schedule.send_digests() == 1
    body = mail.outbox[0].body
    assert mail.outbox[0].subject == "Your day: 2 tasks due today, 2 overdue, 1 client follow-up"
    due_today, overdue = body.split("Overdue (2):")
    assert "Today call 11:00" in due_today and "All-day item" in due_today and "Early meeting" not in due_today
    assert "Early meeting (12/10/2026 08:30)" in overdue and "Late report (09/10/2026)" in overdue


def test_digest_timing_and_no_duplicates(people, digest_data, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        with at_office(DAY, 8, 59):
            assert schedule.send_digests() == 0
        with at_office(DAY, 9, 0):
            assert schedule.send_digests() == 1
        with at_office(DAY, 9, 15):
            assert schedule.send_digests() == 0  # already sent today
        with at_office(DAY + timedelta(days=1), 9, 0):
            assert schedule.send_digests() == 1  # a new day
    assert len(mail.outbox) == 2


def test_digest_catch_up_window(people, digest_data, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        with at_office(DAY, 11, 30):  # the worker came back late in the morning: still sent
            assert schedule.send_digests() == 1
        with at_office(DAY + timedelta(days=1), 14):  # back only in the afternoon: skipped, no stale digest
            assert schedule.send_digests() == 0


def test_digest_with_only_follow_ups(people, django_capture_on_commit_callbacks):
    from apps.contacts.models import Company

    acme = Company.objects.create(name="Acme", assigned_to=people["staff"])
    TimelineEntry.objects.create(kind="note", company=acme, summary="Renewal talk", follow_up_on=DAY, created_by=people["staff"])
    with at_office(DAY, 9, 5), django_capture_on_commit_callbacks(execute=True):
        assert schedule.send_digests() == 1
    assert mail.outbox[0].subject == "Your day: 1 client follow-up"
    assert "Acme: Renewal talk" in mail.outbox[0].body


def test_digest_skipped_when_nothing_to_report(people, django_capture_on_commit_callbacks):
    make("Next month", [people["staff"]], due_date=DAY + timedelta(days=30))
    with at_office(DAY, 9, 5), django_capture_on_commit_callbacks(execute=True):
        assert schedule.send_digests() == 0
    assert not mail.outbox
    assert DigestLog.objects.filter(user=people["staff"], sent=False).exists()  # checked once, not every 15 minutes


def test_digest_respects_preference(people, digest_data, django_capture_on_commit_callbacks):
    NotificationPreference.objects.create(user=digest_data, type="daily_digest", in_app=False, email=False)
    with at_office(DAY, 9, 5), django_capture_on_commit_callbacks(execute=True):
        assert schedule.send_digests() == 0
    assert not mail.outbox


def test_digest_in_urdu(people, digest_data, django_capture_on_commit_callbacks):
    digest_data.language = "ur"
    digest_data.save()
    with at_office(DAY, 9, 5), django_capture_on_commit_callbacks(execute=True):
        schedule.send_digests()
    assert "آج واجب (1):" in mail.outbox[0].body


def test_follow_up_turned_into_a_task_leaves_the_digest(client_for, people, digest_data, django_capture_on_commit_callbacks):
    entry = TimelineEntry.objects.get(summary__startswith="Ask")
    res = client_for(digest_data).post(TASKS, {"title": "Follow up with Ali", "due_date": str(DAY), "follow_up_of": entry.pk, "contact": entry.contact_id}, format="json")
    assert res.status_code == 201 and res.data["follow_up_of"] == entry.pk
    timeline = client_for(digest_data).get("/api/v1/timeline/", {"contact": entry.contact_id, "type": "note"}).data["results"]
    assert next(e for e in timeline if e["entry_id"] == entry.pk)["follow_up_task"]["id"] == res.data["id"]
    with at_office(DAY, 9, 5), django_capture_on_commit_callbacks(execute=True):
        schedule.send_digests()
    assert "Ask about the order" not in mail.outbox[0].body


def test_follow_up_must_be_visible(client_for, people, make_user):
    from apps.contacts.models import Contact

    other = make_user("ops.person@test.com", department="ops")
    hidden = Contact.objects.create(first_name="Hidden", assigned_to=other)
    entry = TimelineEntry.objects.create(kind="note", contact=hidden, summary="x", follow_up_on=DAY, created_by=other)
    res = client_for(people["staff"]).post(TASKS, {"title": "Peek", "follow_up_of": entry.pk}, format="json")
    assert res.status_code == 400


# ================================================================ preferences API


def test_new_preference_types_listed(client_for, people):
    prefs = {p["type"]: p for p in client_for(people["staff"]).get("/api/v1/notifications/preferences/").data}
    assert {"task_assigned", "task_deadline", "task_overdue", "daily_digest"} <= set(prefs)
    assert prefs["daily_digest"]["email"] is True and prefs["daily_digest"]["in_app"] is False


def test_reminder_lead_on_profile(client_for, people):
    c = client_for(people["staff"])
    assert c.get("/api/v1/auth/me/").data["task_reminder_lead"] == "1d"
    assert c.patch("/api/v1/auth/me/", {"task_reminder_lead": "1h"}, format="json").data["task_reminder_lead"] == "1h"
    assert c.patch("/api/v1/auth/me/", {"task_reminder_lead": "2w"}, format="json").status_code == 400


def test_beat_schedules_exist():
    from django_celery_beat.models import PeriodicTask

    tasks = set(PeriodicTask.objects.filter(enabled=True).values_list("task", flat=True))
    assert {"apps.tasks.tasks.send_task_reminders", "apps.tasks.tasks.send_daily_digests", "apps.tasks.tasks.create_recurring_tasks"} <= tasks
