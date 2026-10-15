"""Leave: day counting (weekends, office holidays, half days), balances, requests, approvals, cancelling,
permissions, notifications, the dashboard and calendar. Also Urdu time words in notifications."""
import io
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import translation

from apps.bookings.models import Booking, Resource
from apps.core.models import AuditLog, OrganizationSettings
from apps.core.office_time import clock, office_today, office_tz
from apps.events.models import Event
from apps.events.services import day_bounds
from apps.leave import services
from apps.leave.models import LeaveBalance, LeaveRequest, LeaveType
from apps.notifications.models import Notification, NotificationPreference

pytestmark = pytest.mark.django_db

REQ = "/api/v1/leave/requests/"
BAL = "/api/v1/leave/balances/"
TYPES = "/api/v1/leave/types/"


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {
        "admin": admin, "manager": manager, "staff": staff,
        "colleague": make_user("colleague@test.com", full_name="Sara Colleague", language="ur"),
        "ops": make_user("ops.person@test.com", department="ops", full_name="Omar Ops"),
        "ops_manager": make_user("ops.manager@test.com", role="manager", department="ops", full_name="Olga Manager"),
    }


@pytest.fixture
def annual(db):
    return LeaveType.objects.create(name="Annual leave", name_ur="سالانہ چھٹی", days_per_year=Decimal("5"))


@pytest.fixture
def unpaid(db):
    return LeaveType.objects.create(name="Unpaid leave", days_per_year=None, paid=False, allow_half_days=False)


def monday(weeks=1):
    """A Monday at least a week ahead in this year (or early next year near New Year)."""
    today = office_today()
    d = today + timedelta(days=(7 - today.weekday()) + 7 * (weeks - 1))
    return d


def ask(client, leave_type, first, last=None, **extra):
    body = {"leave_type": leave_type.pk, "start_date": first.isoformat(), "end_date": (last or first).isoformat(), **extra}
    return client.post(REQ, body, format="json")


# ================================================================ counting days


def test_days_skip_weekends_holidays_and_count_half_days(people):
    mon = monday()
    assert services.count_days(mon, mon + timedelta(days=6)).days == 5  # Mon–Sun: Mon–Fri
    start, end = day_bounds(mon + timedelta(days=2), mon + timedelta(days=2))
    Event.objects.create(kind="holiday", title="Eid", all_day=True, start=start, end=end, organizer=people["admin"])
    count = services.count_days(mon, mon + timedelta(days=6))
    assert count.days == 4 and {"date": (mon + timedelta(days=2)).isoformat(), "reason": "holiday", "title": "Eid"} in count.skipped
    assert services.count_days(mon, mon, "morning").days == Decimal("0.5")
    org = OrganizationSettings.get_solo()
    org.working_days = [0, 1, 2, 3, 4, 5]  # a six-day week
    org.save()
    assert services.count_days(mon, mon + timedelta(days=6)).days == 5  # Mon–Sat minus the holiday


# ================================================================ requests and balances


def test_requests_respect_balances_overlaps_and_rules(client_for, people, annual, unpaid):
    staff = client_for(people["staff"])
    mon = monday()
    res = ask(staff, annual, mon, mon + timedelta(days=2))
    assert res.status_code == 201 and res.data["days"] == "3.0" and res.data["status"] == "pending"
    balance = staff.get(BAL).data
    row = next(b for b in balance if b["leave_type"] == annual.pk)
    assert (row["allowance"], row["used"], row["pending"], row["remaining"]) == ("5.0", "0.0", "3.0", "2.0")

    assert ask(staff, annual, mon + timedelta(days=2)).status_code == 400  # overlaps
    too_much = ask(staff, annual, mon + timedelta(days=7), mon + timedelta(days=9))
    assert too_much.status_code == 400 and "leave_type" in too_much.data["errors"]  # 3 > 2 left (pending counts)
    assert ask(staff, annual, mon + timedelta(days=7), mon + timedelta(days=8)).status_code == 201  # exactly 2
    assert ask(staff, unpaid, mon + timedelta(days=14), mon + timedelta(days=18)).status_code == 201  # no limit
    assert ask(staff, unpaid, mon + timedelta(days=21), half_day="morning").status_code == 400  # whole days only
    assert ask(staff, annual, mon + timedelta(days=5), mon + timedelta(days=6)).status_code == 400  # a weekend
    assert ask(staff, annual, mon + timedelta(days=4), mon + timedelta(days=1)).status_code == 400  # backwards
    new_year = date(office_today().year, 12, 31)
    assert ask(staff, unpaid, new_year, new_year + timedelta(days=1)).status_code == 400  # across years

    preview = staff.post(f"{REQ}preview/", {"leave_type": annual.pk, "start_date": mon.isoformat(), "end_date": (mon + timedelta(days=6)).isoformat()}, format="json").data
    assert preview["days"] == "5.0" and len(preview["skipped"]) == 2 and preview["problem"]  # overlaps / too much


def test_half_day_and_admin_allowance_changes(client_for, people, annual):
    staff, admin = client_for(people["staff"]), client_for(people["admin"])
    mon = monday()
    assert ask(staff, annual, mon, half_day="afternoon").data["days"] == "0.5"
    assert ask(staff, annual, mon, mon + timedelta(days=1), half_day="morning").status_code == 400  # one day only
    body = {"user": people["staff"].pk, "leave_type": annual.pk, "year": mon.year, "allowance": "7.5", "note": "Carried over"}
    assert staff.patch(BAL, body, format="json").status_code == 403
    res = admin.patch(BAL, body, format="json")
    assert res.status_code == 200 and res.data["remaining"] == "7.0"
    assert AuditLog.objects.filter(content_type__model="leavebalance", changes__allowance=["5.0", "7.5"]).exists()
    assert admin.patch(BAL, {**body, "allowance": "7.3"}, format="json").status_code == 400


# ================================================================ approvals and cancelling


def test_department_manager_or_admin_decides(client_for, people, annual, django_capture_on_commit_callbacks):
    staff, manager = client_for(people["staff"]), client_for(people["manager"])
    with django_capture_on_commit_callbacks(execute=True):
        req = ask(staff, annual, monday(), monday() + timedelta(days=1), reason="Wedding").data
    asked = Notification.objects.get(type="approval_request")
    assert asked.recipient == people["manager"] and "asks for leave" in asked.title
    assert [m.to for m in mail.outbox] == [["manager@test.com"]]

    url = f"{REQ}{req['id']}/decide/"
    assert staff.post(url, {"approve": True}, format="json").status_code == 403  # not their own
    assert client_for(people["ops_manager"]).post(url, {"approve": True}, format="json").status_code in (403, 404)
    assert manager.get(REQ, {"scope": "approvals"}).data[0]["reason"] == "Wedding"
    with django_capture_on_commit_callbacks(execute=True):
        res = manager.post(url, {"approve": False, "note": "Busy week"}, format="json")
    assert res.data["status"] == "rejected"
    result = Notification.objects.get(type="approval_result", recipient=people["staff"])
    assert result.title == "Leave not approved" and "Busy week" in result.body
    assert manager.post(url, {"approve": True}, format="json").status_code == 403  # already decided
    assert AuditLog.objects.filter(object_id=str(req["id"]), changes__status=["pending", "rejected"]).exists()

    # A manager's own request goes to the admins; an admin's own is approved at once.
    with django_capture_on_commit_callbacks(execute=True):
        own = ask(manager, annual, monday(2)).data
    assert Notification.objects.filter(type="approval_request", recipient=people["admin"]).exists()
    assert manager.post(f"{REQ}{own['id']}/decide/", {"approve": True}, format="json").status_code == 403
    assert ask(client_for(people["admin"]), annual, monday(2)).data["status"] == "approved"


def test_approval_rechecks_the_balance(client_for, people, annual):
    staff, admin = client_for(people["staff"]), client_for(people["admin"])
    first = ask(staff, annual, monday(), monday() + timedelta(days=2)).data  # 3 of 5
    admin.patch(BAL, {"user": people["staff"].pk, "leave_type": annual.pk, "year": monday().year, "allowance": "2"}, format="json")
    res = admin.post(f"{REQ}{first['id']}/decide/", {"approve": True}, format="json")
    assert res.status_code == 400 and LeaveRequest.objects.get(pk=first["id"]).status == "pending"


def test_cancelling(client_for, people, annual, django_capture_on_commit_callbacks):
    staff, manager = client_for(people["staff"]), client_for(people["manager"])
    pending = ask(staff, annual, monday()).data
    assert manager.post(f"{REQ}{pending['id']}/cancel/").status_code == 403  # managers decide, they don't cancel
    assert staff.post(f"{REQ}{pending['id']}/cancel/").data["status"] == "cancelled"
    approved = ask(staff, annual, monday(2)).data
    manager.post(f"{REQ}{approved['id']}/decide/", {"approve": True}, format="json")
    with django_capture_on_commit_callbacks(execute=True):
        assert staff.post(f"{REQ}{approved['id']}/cancel/").status_code == 200
    told = Notification.objects.filter(title__startswith="Leave cancelled").values_list("recipient__email", flat=True)
    assert list(told) == ["manager@test.com"]  # whoever approved it
    # Leave that has started: only an admin cancels it.
    started = LeaveRequest.objects.create(user=people["staff"], leave_type=annual, start_date=office_today() - timedelta(days=1),
                                          end_date=office_today() + timedelta(days=1), days=Decimal("2"), status="approved")
    assert staff.post(f"{REQ}{started.pk}/cancel/").status_code == 403
    assert client_for(people["admin"]).post(f"{REQ}{started.pk}/cancel/").status_code == 200


# ================================================================ permissions, team views, notifications


def test_permissions_and_team_views(client_for, people, annual):
    staff, manager, admin = (client_for(people[k]) for k in ("staff", "manager", "admin"))
    assert staff.post(TYPES, {"name": "Study leave", "days_per_year": "3"}, format="json").status_code == 403
    assert manager.post(TYPES, {"name": "Study leave", "days_per_year": "3"}, format="json").status_code == 403
    created = admin.post(TYPES, {"name": "Study leave", "days_per_year": "3"}, format="json")
    assert created.status_code == 201
    ask(client_for(people["colleague"]), annual, monday())
    ask(client_for(people["ops"]), annual, monday())
    assert [r["user_name"] for r in manager.get(REQ, {"scope": "team"}).data] == ["Sara Colleague"]  # own department only
    assert staff.get(REQ, {"scope": "team"}).data == []
    assert len(admin.get(REQ, {"scope": "team"}).data) == 2
    assert client_for(people["ops"]).get(f"{REQ}{LeaveRequest.objects.get(user=people['colleague']).pk}/").status_code == 404
    manager.post(f"{REQ}{LeaveRequest.objects.get(user=people['colleague']).pk}/decide/", {"approve": True}, format="json")
    team = staff.get("/api/v1/leave/team/", {"from": monday().isoformat(), "to": monday().isoformat()}).data
    assert [t["user_name"] for t in team] == ["Sara Colleague"] and "reason" not in team[0]  # colleagues see dates, not reasons
    assert client_for(people["ops"]).get("/api/v1/leave/team/", {"from": monday().isoformat()}).data == []
    # A used type can't be deleted, only made inactive.
    assert admin.delete(f"{TYPES}{annual.pk}/").status_code == 400
    assert admin.delete(f"{TYPES}{created.data['id']}/").status_code == 204


def test_urdu_reader_gets_urdu_type_and_preferences_apply(client_for, people, annual, django_capture_on_commit_callbacks):
    NotificationPreference.objects.create(user=people["manager"], type="approval_request", in_app=True, email=False)
    with django_capture_on_commit_callbacks(execute=True):
        req = ask(client_for(people["colleague"]), annual, monday()).data
    assert mail.outbox == []  # the manager turned approval emails off
    with django_capture_on_commit_callbacks(execute=True):
        client_for(people["manager"]).post(f"{REQ}{req['id']}/decide/", {"approve": True}, format="json")
    email = mail.outbox[0]
    assert email.to == ["colleague@test.com"] and "سالانہ چھٹی" in email.body  # Urdu reader, Urdu type name


def test_dashboard_pending_approvals_and_calendar_layer(client_for, people, annual):
    ask(client_for(people["staff"]), annual, monday())
    car = Resource.objects.create(name="Car", type="vehicle", needs_approval=True)
    start = datetime.combine(monday(), time(10), tzinfo=office_tz())
    Booking.objects.create(resource=car, title="Trip", booked_by=people["colleague"], start=start, end=start + timedelta(hours=2), status="pending")
    items = client_for(people["manager"]).get("/api/v1/dashboard/").data["pending_approvals"]
    assert [(i["title"], i["badge"]) for i in items] == [("Staff", "Leave"), ("Sara Colleague", "Booking")]
    assert client_for(people["staff"]).get("/api/v1/dashboard/").data["pending_approvals"] == []

    LeaveRequest.objects.filter(user=people["staff"]).update(status="approved")
    feed = client_for(people["colleague"]).get("/api/v1/calendar/", {"from": monday().isoformat(), "to": monday().isoformat(), "layers": "leave"}).data["items"]
    assert [(i["type"], i["title"], i["subtitle"]) for i in feed] == [("leave", "Staff", "Annual leave")]


def test_team_lists_do_not_grow(client_for, people, annual, make_user):
    manager = client_for(people["manager"])

    def count(url, params):
        with CaptureQueriesContext(connection) as ctx:
            assert manager.get(url, params).status_code == 200
        return len(ctx)

    def add(i):
        u = make_user(f"p{i}@test.com")
        LeaveRequest.objects.create(user=u, leave_type=annual, start_date=monday(), end_date=monday(), days=1, status="pending")
        LeaveBalance.objects.create(user=u, leave_type=annual, year=monday().year, allowance=5)

    add(0)
    small = (count(REQ, {"scope": "team"}), count(BAL, {"scope": "team"}), count(REQ, {"scope": "approvals"}))
    for i in range(1, 8):
        add(i)
    assert (count(REQ, {"scope": "team"}), count(BAL, {"scope": "team"}), count(REQ, {"scope": "approvals"})) == small


# ================================================================ Urdu clock (fix)


def test_urdu_texts_use_urdu_parts_of_the_day():
    at = lambda h, m=0: time(h, m)  # noqa: E731
    assert clock(at(9)) == "9:00 am" and clock(at(14, 30)) == "2:30 pm"
    with translation.override("ur"):
        assert [clock(at(h)) for h in (9, 13, 17, 21, 0)] == ["صبح 9:00", "دوپہر 1:00", "شام 5:00", "رات 9:00", "رات 12:00"]
    org = OrganizationSettings.get_solo()
    org.time_format = "24h"
    org.save()
    with translation.override("ur"):
        assert clock(at(17, 30)) == "17:30"  # plain numbers in 24-hour mode


def test_seed_creates_leave(db):
    from django.core.management import call_command

    call_command("seed_demo", stdout=io.StringIO())
    assert LeaveType.objects.count() == 4 and LeaveType.objects.filter(days_per_year__isnull=True).count() == 1
    assert LeaveRequest.objects.filter(status="pending").count() == 2
    assert LeaveBalance.objects.filter(note__icontains="carried").exists()
    assert not Notification.objects.filter(type__in=["approval_request", "approval_result"]).exists()
