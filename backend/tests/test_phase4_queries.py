"""Phase 4 review: every office-planning list and view keeps the same number of queries as the data grows.

One dataset touches every module (resources and bookings with attendees, meetings with rooms, leave,
attendance, supplies and purchase requests, expense claims with receipts, weekly goals with updates).
Each endpoint is measured for an admin, a manager and a staff member with one person's worth of data,
then again after seven more people's worth; the counts must not change.
"""
import io
from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from PIL import Image

from apps.accounts.models import User
from apps.attendance.models import Attendance
from apps.bookings.models import Booking, Resource
from apps.core.office_time import office_today, office_tz
from apps.events.models import Event
from apps.expenses.models import Expense
from apps.expenses.services import save_receipts
from apps.inventory.models import PurchaseRequest, StockMovement, SupplyItem
from apps.leave.models import LeaveBalance, LeaveRequest, LeaveType
from apps.planning.models import GoalUpdate, WeeklyGoal
from apps.planning.services import week_start_of

pytestmark = pytest.mark.django_db


def _png():
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(buf, "PNG")
    return SimpleUploadedFile("r.png", buf.getvalue(), content_type="image/png")


def at(day, hh, mm=0):
    return datetime.combine(day, time(hh, mm), tzinfo=office_tz())


@pytest.fixture
def world(make_user, departments):
    roles = {
        "admin": make_user("a@t.com", User.Role.ADMIN, department=None),
        "manager": make_user("m@t.com", User.Role.MANAGER),
        "staff": make_user("s@t.com"),
    }
    annual = LeaveType.objects.create(name="Annual", name_ur="سالانہ", days_per_year=Decimal("20"))
    return {"roles": roles, "annual": annual, "departments": departments, "make_user": make_user}


def grow(world, i):
    """One more person's worth of everything."""
    today = office_today()
    week = week_start_of(today)
    roles = world["roles"]
    person = world["make_user"](f"p{i}@t.com", department="ops" if i % 2 else "sales")
    resource = Resource.objects.create(name=f"Room {i}", type="room", capacity=4)
    for offset, status in ((1, "confirmed"), (2, "pending"), (-2, "confirmed")):
        b = Booking.objects.create(resource=resource, title=f"B{i}", booked_by=person, status=status,
                                   start=at(today + timedelta(days=offset), 10), end=at(today + timedelta(days=offset), 11))
        b.attendees.set([person, roles["staff"], roles["manager"]])
    meeting = Event.objects.create(kind="meeting", title=f"M{i}", organizer=person, start=at(today + timedelta(days=1), 14),
                                   end=at(today + timedelta(days=1), 15))
    meeting.attendees.set([roles["staff"], roles["manager"], person])
    LeaveRequest.objects.create(user=person, leave_type=world["annual"], start_date=today + timedelta(days=3),
                                end_date=today + timedelta(days=3), days=1, status="pending")
    LeaveRequest.objects.create(user=person, leave_type=world["annual"], start_date=today + timedelta(days=5),
                                end_date=today + timedelta(days=5), days=1, status="approved")
    LeaveBalance.objects.create(user=person, leave_type=world["annual"], year=today.year, allowance=20)
    for d in range(1, 4):
        day = today - timedelta(days=d)
        Attendance.objects.create(user=person, date=day, check_in=at(day, 9), check_out=at(day, 17))
    item = SupplyItem.objects.create(name=f"Item {i}", quantity=i, reorder_level=3)
    StockMovement.objects.create(item=item, kind="received", change=i, quantity_after=i, by=person)
    for status in ("pending", "approved"):
        PurchaseRequest.objects.create(item=item, item_name=item.name, quantity=2, requested_by=person, status=status)
    for status in ("pending", "approved"):
        e = Expense.objects.create(user=person, title=f"E{i}", category="travel", amount=Decimal("100"), currency="PKR",
                                   spent_on=today, status=status)
        save_receipts(e, person, [_png()])
    goal = WeeklyGoal.objects.create(week_start=week, department=person.department, title=f"G{i}", target=5, current=1, owner=person)
    GoalUpdate.objects.create(goal=goal, before=0, after=1, by=person)


def endpoints(world, role):
    today = office_today()
    span = {"from": today.isoformat(), "to": (today + timedelta(days=6)).isoformat()}
    month = today.strftime("%Y-%m")
    out = {
        "resources": ("/api/v1/resources/", {}),
        "bookings timeline": ("/api/v1/bookings/", span),
        "my upcoming bookings": ("/api/v1/bookings/", {"mine": 1, "when": "upcoming"}),
        "my past bookings": ("/api/v1/bookings/", {"mine": 1, "when": "past"}),
        "calendar": ("/api/v1/calendar/", span),
        "leave types": ("/api/v1/leave/types/", {}),
        "my leave": ("/api/v1/leave/requests/", {}),
        "my balances": ("/api/v1/leave/balances/", {}),
        "who's off": ("/api/v1/leave/team/", span),
        "attendance today": ("/api/v1/attendance/today/", {}),
        "my attendance month": ("/api/v1/attendance/month/", {"month": month}),
        "supplies": ("/api/v1/inventory/items/", {}),
        "my purchase requests": ("/api/v1/inventory/requests/", {}),
        "my expenses": ("/api/v1/expenses/claims/", {}),
        "my expense summary": ("/api/v1/expenses/claims/summary/", {}),
        "weekly goals": ("/api/v1/planning/goals/", {}),
        "dashboard": ("/api/v1/dashboard/", {}),
    }
    if role != "staff":
        out |= {
            "booking approvals": ("/api/v1/bookings/", {"approvals": 1}),
            "team leave": ("/api/v1/leave/requests/", {"scope": "team"}),
            "leave approvals": ("/api/v1/leave/requests/", {"scope": "approvals"}),
            "team balances": ("/api/v1/leave/balances/", {"scope": "team"}),
            "attendance team day": ("/api/v1/attendance/team/", {"date": (today - timedelta(days=1)).isoformat()}),
            "attendance team month": ("/api/v1/attendance/team-month/", {"month": month}),
            "all purchase requests": ("/api/v1/inventory/requests/", {"scope": "all"}),
            "purchase approvals": ("/api/v1/inventory/requests/", {"scope": "approvals"}),
            "to receive": ("/api/v1/inventory/requests/", {"scope": "to_receive"}),
            "team expenses": ("/api/v1/expenses/claims/", {"scope": "team"}),
            "expense approvals": ("/api/v1/expenses/claims/", {"scope": "approvals"}),
            "team expense summary": ("/api/v1/expenses/claims/summary/", {"scope": "team"}),
        }
    if role == "admin":
        out["to pay"] = ("/api/v1/expenses/claims/", {"scope": "to_pay"})
    return out


def measure(client, urls):
    counts = {}
    for name, (url, params) in urls.items():
        client.get(url, params)  # warm the settings cache
        with CaptureQueriesContext(connection) as ctx:
            res = client.get(url, params)
        assert res.status_code == 200, (name, res.status_code, getattr(res, "data", None))
        counts[name] = len(ctx)
    return counts


@pytest.mark.parametrize("role", ["admin", "manager", "staff"])
def test_phase4_endpoints_do_not_grow(role, world, client_for):
    client = client_for(world["roles"][role])
    urls = endpoints(world, role)
    grow(world, 0)
    small = measure(client, urls)
    for i in range(1, 8):
        grow(world, i)
    grown = measure(client, urls)
    assert {k: (small[k], grown[k]) for k in small if small[k] != grown[k]} == {}
    assert grown["dashboard"] <= 22
