"""Attendance: day statuses from check-ins, leave, the working week and holidays; checking in and out;
team views and corrections per role; reminders (once a day, not on days off); query counts."""
import io
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.attendance import services, status
from apps.attendance.models import Attendance, AttendanceReminder
from apps.core.models import AuditLog, OrganizationSettings
from apps.core.office_time import office_today, office_tz
from apps.events.models import Event
from apps.events.services import day_bounds
from apps.leave.models import LeaveRequest, LeaveType
from apps.notifications.models import Notification, NotificationPreference

pytestmark = pytest.mark.django_db

A = "/api/v1/attendance/"


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {
        "admin": admin, "manager": manager, "staff": staff,
        "colleague": make_user("colleague@test.com", full_name="Sara Colleague", language="ur"),
        "ops": make_user("ops.person@test.com", department="ops", full_name="Omar Ops"),
        "ops_manager": make_user("ops.manager@test.com", role="manager", department="ops", full_name="Olga Manager"),
    }


def a_weekday(weeks_back=1, weekday=1):
    """A Tuesday (by default) some weeks ago."""
    today = office_today()
    return today - timedelta(days=today.weekday() - weekday + 7 * weeks_back)


def at(day, hh, mm=0):
    return datetime.combine(day, time(hh, mm), tzinfo=office_tz())


def record(user, day, start, end=None, mode="office"):
    return Attendance.objects.create(user=user, date=day, check_in=start, check_out=end, mode=mode)


# ================================================================ statuses


def test_day_statuses(people):
    tue = a_weekday()
    staff, colleague, ops, manager, admin = (people[k] for k in ("staff", "colleague", "ops", "manager", "admin"))
    record(staff, tue, at(tue, 9, 5), at(tue, 17, 30))  # on time (grace 15 min)
    record(colleague, tue, at(tue, 9, 40), mode="remote")  # late
    record(ops, tue, at(tue, 11), mode="field")  # field visits are never "late"
    annual = LeaveType.objects.create(name="Annual", days_per_year=Decimal("10"))
    LeaveRequest.objects.create(user=manager, leave_type=annual, start_date=tue, end_date=tue, days=1, status="approved")
    infos = status.compute([u.pk for u in (staff, colleague, ops, manager, admin)], tue, tue + timedelta(days=4))
    day = lambda u, d=tue: infos[(u.pk, d)]  # noqa: E731
    assert (day(staff)["status"], day(staff)["late"]) == ("present", False)
    assert (day(colleague)["status"], day(colleague)["late"]) == ("remote", True)
    assert (day(ops)["status"], day(ops)["late"]) == ("field", False)
    assert day(manager)["status"] == "leave" and day(manager)["leave"]["type"] == "Annual"
    assert day(admin)["status"] == "absent"
    assert day(admin, tue + timedelta(days=4))["status"] == "off"  # Saturday

    # An office holiday is a day off; today without a check-in is "not in yet", the future "upcoming".
    start, end = day_bounds(tue + timedelta(days=1), tue + timedelta(days=1))
    Event.objects.create(kind="holiday", title="Holiday", all_day=True, start=start, end=end, organizer=admin)
    assert status.compute([admin.pk], tue + timedelta(days=1), tue + timedelta(days=1))[(admin.pk, tue + timedelta(days=1))]["status"] == "off"
    today = office_today()
    now = at(today, 12)
    infos = status.compute([admin.pk], today, today + timedelta(days=7), now=now)
    working = [d for d in (today + timedelta(days=i) for i in range(1, 8)) if d.weekday() < 5]
    assert infos[(admin.pk, working[0])]["status"] == "upcoming"


# ================================================================ checking in and out


def test_check_in_and_out(client_for, people):
    staff = client_for(people["staff"])
    assert staff.post(f"{A}check-out/").status_code == 400  # not checked in yet
    res = staff.post(f"{A}check-in/", {"mode": "field", "note": "Site visit"}, format="json")
    assert res.status_code == 201 and res.data["mode"] == "field"
    assert staff.post(f"{A}check-in/", {}, format="json").status_code == 400  # once a day
    today = staff.get(f"{A}today/").data
    assert today["me"]["status"] == "field" and today["can_check_out"] and not today["can_check_in"]
    assert "team" not in today  # staff don't get team counts
    assert staff.post(f"{A}check-out/").status_code == 200
    assert staff.post(f"{A}check-out/").status_code == 400
    record = Attendance.objects.get(user=people["staff"])
    assert record.check_out > record.check_in
    team = client_for(people["manager"]).get(f"{A}today/").data["team"]
    assert team["field"] == 1 and team["not_in"] + team["off"] + team["leave"] + team["absent"] >= 1  # manager, colleague


# ================================================================ team views and corrections


def test_team_views_and_corrections_per_role(client_for, people, django_capture_on_commit_callbacks):
    tue = a_weekday()
    staff, manager, admin = (client_for(people[k]) for k in ("staff", "manager", "admin"))
    assert staff.get(f"{A}team/").status_code == 403
    assert staff.get(f"{A}month/", {"user": people["colleague"].pk}).status_code == 403
    names = [r["user_name"] for r in manager.get(f"{A}team/", {"date": tue.isoformat()}).data["rows"]]
    assert names == ["Manager", "Sara Colleague", "Staff"]  # own department (themselves included)
    assert len(admin.get(f"{A}team/", {"date": tue.isoformat()}).data["rows"]) == 6
    assert manager.get(f"{A}month/", {"user": people["ops"].pk}).status_code == 403
    assert manager.get(f"{A}month/", {"user": people["colleague"].pk}).status_code == 200

    body = {"user": people["colleague"].pk, "date": tue.isoformat(), "check_in": "09:10", "check_out": "17:45", "mode": "office"}
    assert staff.post(f"{A}correct/", body, format="json").status_code == 403
    assert manager.post(f"{A}correct/", {**body, "user": people["ops"].pk}, format="json").status_code == 403  # other department
    assert manager.post(f"{A}correct/", {**body, "check_out": "09:00"}, format="json").status_code == 400
    assert manager.post(f"{A}correct/", {**body, "date": (office_today() + timedelta(days=2)).isoformat()}, format="json").status_code == 400
    with django_capture_on_commit_callbacks(execute=True):
        res = manager.post(f"{A}correct/", body, format="json")
    assert res.status_code == 200 and res.data["status"] == "present" and res.data["corrected"]
    note = Notification.objects.get(type="attendance", recipient=people["colleague"])
    assert "صبح 9:10–شام 5:45" in note.body  # an Urdu reader: Urdu parts of the day
    entry = AuditLog.objects.get(description="Attendance corrected")
    assert entry.changes["check_in"][0] is None and entry.object_repr.startswith("Sara Colleague")
    activity = manager.get("/api/v1/dashboard/").data["activity"]
    assert not [a for a in activity if a["description"] == "Attendance corrected"]  # not team news
    with django_capture_on_commit_callbacks(execute=True):
        res = manager.post(f"{A}correct/", {**body, "clear": True}, format="json")
    assert res.data["status"] == "absent" and not Attendance.objects.filter(user=people["colleague"]).exists()

    grid = admin.get(f"{A}team-month/", {"month": tue.strftime("%Y-%m")}).data
    assert len(grid["rows"]) == 6 and len(grid["rows"][0]["cells"]) == len(grid["days"])


# ================================================================ reminders


def test_reminders_once_and_only_on_working_days(people):
    tue = a_weekday(0) if a_weekday(0) <= office_today() else a_weekday()
    staff, colleague, manager = people["staff"], people["colleague"], people["manager"]
    record(staff, tue, at(tue, 9))
    annual = LeaveType.objects.create(name="Annual", days_per_year=Decimal("10"))
    LeaveRequest.objects.create(user=manager, leave_type=annual, start_date=tue, end_date=tue, days=1, status="approved")
    assert services.send_reminders(at(tue, 9, 20)) == {"in": 0, "out": 0}  # too early (threshold 9:15 + 15 min)
    sent = services.send_reminders(at(tue, 9, 35))
    reminded = set(Notification.objects.filter(title="Forgot to check in?").values_list("recipient__email", flat=True))
    assert sent["in"] == 4 and "staff@test.com" not in reminded and "manager@test.com" not in reminded  # checked in / on leave
    assert services.send_reminders(at(tue, 10)) == {"in": 0, "out": 0}  # once a day
    out = services.send_reminders(at(tue, 18, 31))
    assert out == {"in": 0, "out": 1} and Notification.objects.filter(recipient=staff, title="Forgot to check out?").exists()
    assert services.send_reminders(at(tue, 19)) == {"in": 0, "out": 0}
    # Not on a Saturday, and not when switched off.
    sat = tue + timedelta(days=4)
    assert services.send_reminders(at(sat, 11)) == {"in": 0, "out": 0}
    org = OrganizationSettings.get_solo()
    org.attendance_reminders = False
    org.save()
    assert services.send_reminders(at(tue + timedelta(days=1), 11)) == {"in": 0, "out": 0}


def test_reminders_follow_preferences(people, django_capture_on_commit_callbacks):
    tue = a_weekday()
    NotificationPreference.objects.create(user=people["staff"], type="attendance", in_app=True, email=True)
    with django_capture_on_commit_callbacks(execute=True):
        services.send_reminders(at(tue, 10))
    assert [m.to for m in mail.outbox] == [["staff@test.com"]]  # email is off by default, on for this person
    assert "9:00 am" in mail.outbox[0].body
    assert AttendanceReminder.objects.filter(date=tue, kind="in").count() == 6


# ================================================================ query counts and seed


def test_team_views_do_not_grow(client_for, people, make_user):
    manager = client_for(people["manager"])
    tue = a_weekday()

    def count(url, params):
        with CaptureQueriesContext(connection) as ctx:
            assert manager.get(url, params).status_code == 200
        return len(ctx)

    def add(i):
        u = make_user(f"p{i}@test.com")
        for d in range(5):
            day = tue - timedelta(days=d)
            record(u, day, at(day, 9), at(day, 17))

    add(0)
    params = ({"date": tue.isoformat()}, {"month": tue.strftime("%Y-%m")})
    small = (count(f"{A}team/", params[0]), count(f"{A}team-month/", params[1]), count(f"{A}today/", {}))
    for i in range(1, 8):
        add(i)
    assert (count(f"{A}team/", params[0]), count(f"{A}team-month/", params[1]), count(f"{A}today/", {})) == small


def test_seed_creates_attendance(db):
    from django.core.management import call_command

    call_command("seed_demo", stdout=io.StringIO())
    assert Attendance.objects.filter(mode="field").exists() and Attendance.objects.count() > 30
    assert not Attendance.objects.filter(date__gt=office_today()).exists()
    assert not Attendance.objects.filter(check_in__gt=timezone.now()).exists()
    assert date.today().year >= 2026
