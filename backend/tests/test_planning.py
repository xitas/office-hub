"""Weekly planning: who plans and sees which goals, progress with history and audit, notifications
(owner, goal reached, end-of-week reminder with Urdu time words), carrying over, query counts, seed."""
import io
from datetime import datetime, time, timedelta

import pytest
from django.core import mail
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.core.models import AuditLog, OrganizationSettings
from apps.core.office_time import office_today, office_tz
from apps.notifications.models import Notification, NotificationPreference
from apps.planning import services
from apps.planning.models import GoalReminder, WeeklyGoal

pytestmark = pytest.mark.django_db

URL = "/api/v1/planning/goals/"


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {
        "admin": admin, "manager": manager, "staff": staff,
        "colleague": make_user("colleague@test.com", full_name="Sara Colleague", language="ur"),
        "ops": make_user("ops.person@test.com", department="ops", full_name="Omar Ops"),
        "ops_manager": make_user("ops.manager@test.com", role="manager", department="ops", full_name="Olga Manager"),
    }


def this_week():
    return services.week_start_of(office_today())


def goal(client, departments, **data):
    body = {"week_start": office_today().isoformat(), "department": departments["sales"].pk, "title": "Send quotations",
            "target": 5, "unit": "quotations", **data}
    return client.post(URL, body, format="json")


# ================================================================ planning and seeing


def test_who_plans_and_sees_what(client_for, people, departments):
    staff, manager, ops_manager, admin = (client_for(people[k]) for k in ("staff", "manager", "ops_manager", "admin"))
    assert goal(staff, departments).status_code == 403
    assert goal(manager, departments, department=departments["ops"].pk).status_code == 403  # not their department
    assert goal(manager, departments, department=None).status_code == 403  # office-wide: admins
    assert goal(manager, departments, owner=people["ops"].pk).status_code == 400  # owner from another department
    last_week = (this_week() - timedelta(days=7)).isoformat()
    assert goal(manager, departments, week_start=last_week).status_code == 400
    res = goal(manager, departments, owner=people["staff"].pk)
    assert res.status_code == 201 and res.data["week_start"] == this_week().isoformat()  # any day → the week's start
    assert goal(ops_manager, departments, department=departments["ops"].pk, title="Site visits").status_code == 201
    assert goal(admin, departments, department=None, title="Fire drill", target=1, unit="").status_code == 201
    titles = lambda c: sorted(g["title"] for g in c.get(URL).data["goals"])  # noqa: E731
    assert titles(staff) == ["Fire drill", "Send quotations"]  # own department and office-wide
    assert titles(client_for(people["ops"])) == ["Fire drill", "Site visits"]
    assert len(admin.get(URL).data["goals"]) == 3
    assert [g["title"] for g in admin.get(URL, {"department": "office"}).data["goals"]] == ["Fire drill"]
    pk = res.data["id"]
    assert ops_manager.patch(f"{URL}{pk}/", {"title": "Mine now"}, format="json").status_code == 404  # can't even see it
    assert staff.patch(f"{URL}{pk}/", {"title": "x"}, format="json").status_code == 403
    assert manager.patch(f"{URL}{pk}/", {"target": 6}, format="json").data["target"] == 6
    assert AuditLog.objects.filter(object_id=str(pk), action="update", changes__target=[5, 6]).exists()
    assert manager.delete(f"{URL}{pk}/").status_code == 204


def test_progress_owner_notifications_and_history(client_for, people, departments, django_capture_on_commit_callbacks):
    manager, staff, colleague = (client_for(people[k]) for k in ("manager", "staff", "colleague"))
    with django_capture_on_commit_callbacks(execute=True):
        pk = goal(manager, departments, owner=people["colleague"].pk, target=3).data["id"]
    told = Notification.objects.get(type="planning", recipient=people["colleague"])
    assert told.title == "آپ کے لیے نیا ہفتہ وار ہدف" and "Send quotations · 0/3 quotations" in told.body
    progress = f"{URL}{pk}/progress/"
    assert staff.post(progress, {"add": 1}, format="json").status_code == 403  # not the owner
    assert colleague.post(progress, {"add": 1, "value": 2}, format="json").status_code == 400  # one or the other
    assert colleague.post(progress, {"add": -1}, format="json").status_code == 400  # below zero
    assert colleague.post(progress, {"add": 2, "note": "Two sent"}, format="json").data["current"] == 2
    with django_capture_on_commit_callbacks(execute=True):
        res = colleague.post(progress, {"value": 3}, format="json")
    assert res.data["done"] and res.data["completed_at"]
    done = Notification.objects.get(type="planning", recipient=people["manager"])  # the manager hears it's reached
    assert done.title == "Goal reached: Send quotations"
    assert [(h["before"], h["after"]) for h in staff.get(f"{URL}{pk}/history/").data] == [(2, 3), (0, 2)]
    assert AuditLog.objects.filter(description="Progress updated", changes__current=[2, 3]).exists()
    # Raising the target re-opens it.
    assert manager.patch(f"{URL}{pk}/", {"target": 4}, format="json").data["completed_at"] is None


def test_carry_over(client_for, people, departments):
    manager, admin = client_for(people["manager"]), client_for(people["admin"])
    week = this_week()
    a = WeeklyGoal.objects.create(week_start=week, department=departments["sales"], title="Quotations", target=5, current=3, unit="q", owner=people["staff"])
    WeeklyGoal.objects.create(week_start=week, department=departments["sales"], title="Done", target=1, current=1)
    WeeklyGoal.objects.create(week_start=week, department=departments["ops"], title="Ops goal", target=2)
    body = {"week_start": week.isoformat(), "department": departments["sales"].pk}
    res = manager.post(f"{URL}carry-over/", body, format="json")
    assert res.status_code == 201 and [(g["title"], g["target"], g["current"]) for g in res.data] == [("Quotations", 2, 0)]
    assert res.data[0]["owner"] == people["staff"].pk and res.data[0]["carried_from"] == a.pk
    assert manager.post(f"{URL}carry-over/", body, format="json").data == []  # once
    assert manager.post(f"{URL}carry-over/", {**body, "department": departments["ops"].pk}, format="json").status_code == 403
    assert manager.post(f"{URL}carry-over/", {**body, "all_departments": True}, format="json").status_code == 403
    assert [g["title"] for g in admin.post(f"{URL}carry-over/", {**body, "all_departments": True}, format="json").data] == ["Ops goal"]


def test_end_of_week_reminder(people, departments, django_capture_on_commit_callbacks):
    week = this_week()
    last = services.last_working_day(week)
    OrganizationSettings.objects.update(working_days=[0, 1, 2, 3, 4])
    NotificationPreference.objects.create(user=people["colleague"], type="planning", in_app=True, email=True)
    WeeklyGoal.objects.create(week_start=week, department=departments["sales"], title="Quotations", target=5, current=1, owner=people["colleague"])
    WeeklyGoal.objects.create(week_start=week, department=departments["sales"], title="Calls", target=2, current=2, owner=people["staff"])
    at = lambda day, hh: datetime.combine(day, time(hh), tzinfo=office_tz())  # noqa: E731
    assert services.send_reminders(at(last, 15)) == 0  # closes at 18:00: from 16:00
    assert services.send_reminders(at(last - timedelta(days=1), 17)) == 0  # not the last working day
    with django_capture_on_commit_callbacks(execute=True):
        assert services.send_reminders(at(last, 16)) == 1  # the staff member's goal is done: nothing for them
    assert services.send_reminders(at(last, 17)) == 0  # once a week
    note = Notification.objects.get(type="planning", recipient=people["colleague"])
    assert "شام 6:00" in note.body and "Quotations" in note.body  # Urdu reader: Urdu part of the day
    assert [m.to for m in mail.outbox] == [["colleague@test.com"]]
    assert GoalReminder.objects.filter(week_start=week).count() == 1


def test_week_list_does_not_grow(client_for, people, departments, make_user):
    admin = client_for(people["admin"])
    week = this_week()

    def count():
        with CaptureQueriesContext(connection) as ctx:
            assert admin.get(URL).status_code == 200
        return len(ctx)

    def add(i):
        owner = make_user(f"o{i}@test.com", department="ops" if i % 2 else "sales")
        WeeklyGoal.objects.create(week_start=week, department=owner.department, title=f"Goal {i}", target=3, owner=owner)

    add(0)
    small = count()
    for i in range(1, 10):
        add(i)
    assert count() == small


def test_seed_creates_goals(db):
    from django.core.management import call_command

    call_command("seed_demo", stdout=io.StringIO())
    week = this_week()
    assert WeeklyGoal.objects.filter(week_start=week).count() >= 6
    assert WeeklyGoal.objects.filter(week_start=week - timedelta(days=7), current__lt=1).exists()  # something to carry over
    assert WeeklyGoal.objects.filter(department__isnull=True).exists()
