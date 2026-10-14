"""Rooms and resource booking: overlaps (also two requests at the same moment on PostgreSQL), office
hours and limits, approvals, weekly repeats with conflicts, permissions, notifications and reminders."""
import io
import threading
from datetime import datetime, timedelta

import pytest
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.bookings import services
from apps.bookings.models import Booking, Resource
from apps.core.models import OrganizationSettings
from apps.core.office_time import office_today, office_tz
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db

URL = "/api/v1/bookings/"
RES = "/api/v1/resources/"
on_postgres = pytest.mark.skipif(connection.vendor != "postgresql", reason="needs PostgreSQL (exclusion constraint, row locks)")


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {
        "admin": admin, "manager": manager, "staff": staff,
        "colleague": make_user("colleague@test.com", full_name="Sara Colleague"),
        "ops": make_user("ops.person@test.com", department="ops", full_name="Omar Ops"),
        "ops_manager": make_user("ops.manager@test.com", role="manager", department="ops", full_name="Olga Manager"),
    }


@pytest.fixture
def room(db):
    return Resource.objects.create(name="Board room", type="room", capacity=10)


@pytest.fixture
def car(db, departments):
    car = Resource.objects.create(name="Corolla", type="vehicle", needs_approval=True, bookable_by="departments")
    car.departments.set([departments["sales"]])
    return car


def at(day_offset, hhmm):
    """An office-local moment `day_offset` days from today."""
    day = office_today() + timedelta(days=day_offset)
    return datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time(), tzinfo=office_tz())


def book(client, resource, start, end, **extra):
    body = {"resource": resource.pk, "title": extra.pop("title", "Meeting"), "start": start.isoformat(), "end": end.isoformat(), **extra}
    return client.post(URL, body, format="json")


def make(resource, user, start, end, status="confirmed", **extra):
    return Booking.objects.create(resource=resource, booked_by=user, title=extra.pop("title", "Seeded"), start=start, end=end, status=status, **extra)


# ================================================================ overlaps


def test_no_overlapping_bookings_of_one_resource(client_for, people, room, make_user):
    staff, colleague = client_for(people["staff"]), client_for(people["colleague"])
    assert book(staff, room, at(1, "10:00"), at(1, "11:00")).status_code == 201
    res = book(colleague, room, at(1, "10:30"), at(1, "11:30"))
    assert res.status_code == 409 and res.data["conflict"]["booked_by_name"] == people["staff"].full_name
    assert book(colleague, room, at(1, "09:00"), at(1, "12:00")).status_code == 409  # around it
    assert book(colleague, room, at(1, "11:00"), at(1, "12:00")).status_code == 201  # touching is fine
    other = Resource.objects.create(name="Room B")
    assert book(colleague, other, at(1, "10:00"), at(1, "11:00")).status_code == 201  # another resource
    # Cancelling frees the time.
    first = Booking.objects.get(start=at(1, "10:00"), resource=room)
    assert staff.post(f"{URL}{first.pk}/cancel/").status_code == 200
    assert book(colleague, room, at(1, "10:00"), at(1, "11:00")).status_code == 201


@on_postgres
def test_database_refuses_overlaps_itself(people, room):
    make(room, people["staff"], at(1, "10:00"), at(1, "11:00"))
    with pytest.raises(IntegrityError), transaction.atomic():
        make(room, people["colleague"], at(1, "10:45"), at(1, "11:15"))
    make(room, people["colleague"], at(1, "10:45"), at(1, "11:15"), status="cancelled")  # cancelled ones don't count
    with pytest.raises(IntegrityError), transaction.atomic():
        make(room, people["colleague"], at(1, "10:30"), at(1, "10:45"), status="pending")  # pending ones hold the time


@on_postgres
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("with_lock", [True, False], ids=["row-lock", "constraint-only"])
def test_two_simultaneous_requests_only_one_wins(make_user, departments, monkeypatch, with_lock):
    """Two people press "Book" for the same slot at the same moment: exactly one booking is made.
    Also without the row lock, so the database constraint alone is shown to hold."""
    room = Resource.objects.create(name="Board room")
    a, b = make_user("a@test.com"), make_user("b@test.com")
    if not with_lock:
        monkeypatch.setattr(services, "_lock", lambda resource: None)
    gate = threading.Barrier(2)
    results = {}

    def request(user):
        client = APIClient()
        client.force_authenticate(user)
        gate.wait()
        try:
            results[user.email] = book(client, room, at(1, "10:00"), at(1, "11:00")).status_code
        finally:
            connection.close()

    threads = [threading.Thread(target=request, args=(u,)) for u in (a, b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(results.values()) == [201, 409]
    assert Booking.objects.filter(resource=room).count() == 1


# ================================================================ office hours and limits


def test_office_hours_slots_and_limits(client_for, people, room):
    staff, admin = client_for(people["staff"]), client_for(people["admin"])

    def refused(client, start, end):
        res = book(client, room, start, end)
        return res.status_code == 400 and res.data["errors"]

    assert refused(staff, at(1, "08:00"), at(1, "09:00"))  # before opening (09:00)
    assert refused(staff, at(1, "17:30"), at(1, "18:15"))  # after closing (18:00)
    assert refused(staff, at(1, "10:05"), at(1, "11:00"))  # not a 15-minute step
    assert refused(staff, at(1, "11:00"), at(1, "11:00"))  # zero length
    assert refused(staff, at(1, "12:00"), at(1, "11:00"))  # backwards
    assert refused(staff, at(-1, "10:00"), at(-1, "11:00"))  # the past
    assert book(staff, room, at(1, "17:00"), at(1, "18:00")).status_code == 201  # up to closing time

    org = OrganizationSettings.get_solo()
    org.booking_max_minutes, org.booking_horizon_days = 120, 7
    org.office_opens, org.office_closes = datetime.strptime("08:00", "%H:%M").time(), datetime.strptime("20:00", "%H:%M").time()
    org.save()
    assert book(staff, room, at(1, "08:00"), at(1, "09:00")).status_code == 201  # new opening hour applies
    assert refused(staff, at(2, "09:00"), at(2, "11:15"))  # longer than 2 hours
    assert refused(staff, at(9, "09:00"), at(9, "10:00"))  # more than 7 days ahead
    # Admins are exempt from the length and "how far ahead" limits (not from office hours).
    assert book(admin, room, at(2, "09:00"), at(2, "12:00")).status_code == 201
    assert book(admin, room, at(9, "09:00"), at(9, "10:00")).status_code == 201
    assert refused(admin, at(3, "20:00"), at(3, "21:00"))


def test_office_hours_settings_are_validated(client_for, people):
    admin = client_for(people["admin"])
    url = "/api/v1/settings/organization/"
    assert admin.patch(url, {"office_opens": "18:00", "office_closes": "09:00"}, format="json").status_code == 400
    assert admin.patch(url, {"office_opens": "09:10"}, format="json").status_code == 400
    assert admin.patch(url, {"booking_max_minutes": 100}, format="json").status_code == 400
    res = admin.patch(url, {"office_opens": "08:30", "office_closes": "17:30", "booking_max_minutes": 240, "booking_horizon_days": 30}, format="json")
    assert res.status_code == 200 and res.data["office_opens"] == "08:30:00"
    assert client_for(people["staff"]).patch(url, {"office_opens": "08:00"}, format="json").status_code == 403


# ================================================================ approvals


def test_approval_by_department_manager_or_admin(client_for, people, car, django_capture_on_commit_callbacks):
    staff = client_for(people["staff"])
    with django_capture_on_commit_callbacks(execute=True):
        res = book(staff, car, at(1, "10:00"), at(1, "12:00"), title="Client visit")
    booking = res.data["bookings"][0]
    assert booking["status"] == "pending"
    request = Notification.objects.get(type="approval_request")
    assert request.recipient == people["manager"] and "Corolla" in request.title  # the Sales manager is asked
    # A pending request holds the time.
    assert book(client_for(people["colleague"]), car, at(1, "11:00"), at(1, "13:00")).status_code == 409

    url = f"{URL}{booking['id']}/decide/"
    assert staff.post(url, {"approve": True}, format="json").status_code == 403  # not their own
    assert client_for(people["ops_manager"]).post(url, {"approve": True}, format="json").status_code in (403, 404)  # other department
    assert client_for(people["manager"]).get(URL, {"approvals": "1"}).data[0]["id"] == booking["id"]
    with django_capture_on_commit_callbacks(execute=True):
        res = client_for(people["manager"]).post(url, {"approve": True}, format="json")
    assert res.status_code == 200 and res.data["status"] == "confirmed" and res.data["decided_by_name"] == people["manager"].full_name
    result = Notification.objects.get(type="approval_result", recipient=people["staff"])
    assert "approved" in result.title
    assert client_for(people["manager"]).post(url, {"approve": False}, format="json").status_code == 403  # already decided

    # Rejected with a reason: the requester is told why, and the time is free again.
    with django_capture_on_commit_callbacks(execute=True):
        second = book(staff, car, at(2, "10:00"), at(2, "11:00")).data["bookings"][0]
        client_for(people["admin"]).post(f"{URL}{second['id']}/decide/", {"approve": False, "reason": "Car is in for service"}, format="json")
    rejected = Notification.objects.filter(type="approval_result", recipient=people["staff"]).order_by("-id").first()
    assert "rejected" in rejected.title and "Car is in for service" in rejected.body
    assert book(client_for(people["colleague"]), car, at(2, "10:00"), at(2, "11:00")).status_code == 201


def test_managers_requests_go_to_admins_and_admins_need_no_approval(client_for, people, car, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        pending = book(client_for(people["manager"]), car, at(1, "10:00"), at(1, "11:00")).data["bookings"][0]
    assert Notification.objects.get(type="approval_request").recipient == people["admin"]
    assert client_for(people["manager"]).post(f"{URL}{pending['id']}/decide/", {"approve": True}, format="json").status_code == 403
    assert book(client_for(people["admin"]), car, at(1, "13:00"), at(1, "14:00")).data["bookings"][0]["status"] == "confirmed"


# ================================================================ weekly repeats


def test_weekly_repeat_lists_conflicts_and_can_skip_them(client_for, people, room):
    staff = client_for(people["staff"])
    start = at(1, "10:00")
    weekday = start.weekday()
    until = (start + timedelta(weeks=3)).date()
    taken = make(room, people["colleague"], start + timedelta(weeks=2), at(1, "11:00") + timedelta(weeks=2), title="Board meeting")
    repeat = {"weekdays": [weekday], "until": until.isoformat()}

    check = staff.post(f"{URL}check/", {"resource": room.pk, "title": "Stand-up", "start": start.isoformat(),
                                         "end": at(1, "11:00").isoformat(), "repeat": repeat}, format="json")
    dates = check.data["occurrences"]
    assert len(dates) == 4 and [d["problem"] for d in dates] == [None, None, "conflict", None]
    assert dates[2]["conflict"]["title"] == "Board meeting"

    res = book(staff, room, start, at(1, "11:00"), title="Stand-up", repeat=repeat)
    assert res.status_code == 409 and len(res.data["occurrences"]) == 4
    assert not Booking.objects.filter(title="Stand-up").exists()  # nothing saved until the clash is resolved

    res = book(staff, room, start, at(1, "11:00"), title="Stand-up", repeat=repeat, skip_conflicts=True)
    assert res.status_code == 201 and len(res.data["bookings"]) == 3 and len(res.data["skipped"]) == 1
    series = Booking.objects.filter(title="Stand-up").order_by("start")
    assert series.count() == 3 and len({b.series_id for b in series}) == 1
    assert taken.start not in [b.start for b in series]

    # Cancel "this and following" from the second date.
    second = series[1]
    assert staff.post(f"{URL}{second.pk}/cancel/", {"following": True}, format="json").data["cancelled"] == [b.pk for b in series[1:]]
    assert Booking.objects.get(pk=series[0].pk).status == "confirmed"


def test_weekly_repeat_on_several_days_respects_the_horizon(client_for, people, room):
    org = OrganizationSettings.get_solo()
    org.booking_horizon_days = 10
    org.save()
    start = at(1, "09:00")
    days = sorted({start.weekday(), (start.weekday() + 2) % 7})
    res = book(client_for(people["staff"]), room, start, at(1, "09:30"), repeat={"weekdays": days, "until": (start + timedelta(days=20)).date().isoformat()})
    assert res.status_code == 409
    problems = [o["problem"] for o in res.data["occurrences"]]
    assert "rules" in problems and problems[0] is None  # later dates are too far ahead


# ================================================================ permissions


def test_permissions_per_role(client_for, people, room, car):
    staff, admin, ops = client_for(people["staff"]), client_for(people["admin"]), client_for(people["ops"])
    assert staff.post(RES, {"name": "New room", "type": "room"}, format="json").status_code == 403
    assert client_for(people["manager"]).post(RES, {"name": "New room", "type": "room"}, format="json").status_code == 403
    assert admin.post(RES, {"name": "New room", "type": "room", "capacity": 4}, format="json").status_code == 201
    assert staff.patch(f"{RES}{room.pk}/", {"name": "Mine"}, format="json").status_code == 403

    # The car is for Sales only: invisible and not bookable for Operations.
    assert car.pk not in [r["id"] for r in ops.get(RES).data]
    assert book(ops, car, at(1, "10:00"), at(1, "11:00")).status_code == 400
    # Inactive resources: hidden from staff, kept for admins.
    room.is_active = False
    room.save()
    assert room.pk not in [r["id"] for r in staff.get(RES).data] and room.pk in [r["id"] for r in admin.get(RES).data]
    assert book(admin, room, at(1, "10:00"), at(1, "11:00")).status_code == 400
    room.is_active = True
    room.save()

    booking = book(staff, room, at(1, "10:00"), at(1, "11:00")).data["bookings"][0]
    url = f"{URL}{booking['id']}/"
    assert client_for(people["colleague"]).patch(url, {"title": "Hijack"}, format="json").status_code == 403
    assert client_for(people["colleague"]).post(f"{url}cancel/").status_code == 403
    assert client_for(people["manager"]).post(f"{url}cancel/").status_code == 403  # managers don't cancel others' bookings
    assert staff.patch(url, {"title": "Renamed"}, format="json").data["title"] == "Renamed"
    assert admin.post(f"{url}cancel/").status_code == 200
    # A resource with bookings can't be deleted (make it inactive instead).
    assert admin.delete(f"{RES}{room.pk}/").status_code == 400


def test_resource_photo_follows_the_image_rules(client_for, people):
    admin = client_for(people["admin"])
    buf = io.BytesIO()
    Image.new("RGB", (60, 40), "green").save(buf, "PNG")
    buf.seek(0)
    buf.name = "room.png"
    res = admin.post(RES, {"name": "Room C", "type": "room", "photo": buf}, format="multipart")
    assert res.status_code == 201 and res.data["thumbnail_url"]
    thumb = client_for(people["staff"]).get(f"/api/v1{res.data['thumbnail_url']}")
    assert thumb.status_code == 200 and thumb["Content-Type"] == "image/webp", thumb.content[:200]
    pdf = io.BytesIO(b"%PDF-1.4 not a photo")
    pdf.name = "plan.pdf"
    assert admin.patch(f"{RES}{res.data['id']}/", {"photo": pdf}, format="multipart").status_code == 400


# ================================================================ notifications and reminders


def test_attendees_and_booker_hear_about_changes(client_for, people, room, django_capture_on_commit_callbacks):
    staff = client_for(people["staff"])
    with django_capture_on_commit_callbacks(execute=True):
        booking = book(staff, room, at(1, "10:00"), at(1, "11:00"), attendees=[people["colleague"].pk, people["staff"].pk]).data["bookings"][0]
    assert booking["attendees"] == [people["colleague"].pk]  # the booker isn't their own attendee
    assert Notification.objects.filter(type="booking", recipient=people["colleague"], title__contains="booked Board room").exists()

    with django_capture_on_commit_callbacks(execute=True):
        res = staff.patch(f"{URL}{booking['id']}/", {"start": at(1, "14:00").isoformat(), "end": at(1, "15:00").isoformat(),
                                                     "attendees": [people["colleague"].pk, people["manager"].pk]}, format="json")
    assert res.status_code == 200
    changed = Notification.objects.get(type="booking", recipient=people["colleague"], title__startswith="Booking changed")
    assert "2:00 pm–3:00 pm" in changed.body  # the organization's clock (12-hour by default)
    org = OrganizationSettings.get_solo()
    org.time_format = "24h"
    org.save()
    changed.refresh_from_db()
    from apps.notifications.services import display_text

    assert "14:00–15:00" in display_text(changed)[1]  # re-rendered with the 24-hour clock
    assert Notification.objects.filter(recipient=people["manager"], title__contains="booked Board room").exists()  # newly invited
    assert not Notification.objects.filter(recipient=people["staff"]).exists()  # nobody is told about their own action

    with django_capture_on_commit_callbacks(execute=True):
        client_for(people["admin"]).post(f"{URL}{booking['id']}/cancel/")
    cancelled = set(Notification.objects.filter(title__startswith="Booking cancelled").values_list("recipient__email", flat=True))
    assert cancelled == {"staff@test.com", "colleague@test.com", "manager@test.com"}


def test_reminders_15_minutes_before_once(people, room):
    now = timezone.now()
    soon = make(room, people["staff"], now + timedelta(minutes=10), now + timedelta(minutes=40))
    soon.attendees.set([people["colleague"]])
    other_room = Resource.objects.create(name="Room B")
    make(other_room, people["colleague"], now + timedelta(minutes=40), now + timedelta(minutes=70))  # too early to remind
    make(room, people["manager"], now + timedelta(minutes=5), now + timedelta(minutes=8), status="pending")  # not confirmed
    assert services.send_reminders(now) == 1
    reminded = set(Notification.objects.filter(title__startswith="Starts in 15 minutes").values_list("recipient__email", flat=True))
    assert reminded == {"staff@test.com", "colleague@test.com"}
    assert services.send_reminders(now) == 0  # never twice
    assert services.send_reminders(now + timedelta(minutes=1)) == 0
    # Moved to a new time: a new reminder when that one comes close.
    Booking.objects.filter(pk=soon.pk).update(start=now + timedelta(minutes=50), end=now + timedelta(minutes=80))
    assert services.send_reminders(now + timedelta(minutes=36)) == 2  # the moved one and the 40-minute one


# ================================================================ lists and dashboard


def test_dashboard_widgets(client_for, people, room, car):
    today = office_today()
    # Bookings made directly so they can be "today" whatever the clock says.
    start = datetime.combine(today, datetime.strptime("10:00", "%H:%M").time(), tzinfo=office_tz())
    mine = make(room, people["staff"], start, start + timedelta(hours=1), title="Mine")
    invited = make(room, people["manager"], start + timedelta(hours=2), start + timedelta(hours=3), title="Invited")
    invited.attendees.set([people["staff"]])
    make(car, people["colleague"], start, start + timedelta(hours=2), title="Car trip", status="pending")
    make(room, people["manager"], start + timedelta(days=1), start + timedelta(days=1, hours=1), title="Tomorrow")
    data = client_for(people["staff"]).get("/api/v1/dashboard/").data
    assert [i["title"] for i in data["bookings_today"]] == ["Mine", "Invited"]
    assert [i["title"] for i in data["meetings_today"]] == ["Mine", "Invited"]  # confirmed only
    ops = client_for(people["ops"]).get("/api/v1/dashboard/").data
    assert ops["bookings_today"] == [] and "Car trip" not in [i["title"] for i in ops["meetings_today"]]


def test_lists_and_query_counts(client_for, people, room, make_user):
    client = client_for(people["staff"])
    params = {"from": office_today().isoformat(), "to": (office_today() + timedelta(days=6)).isoformat()}
    assert client.get(URL).status_code == 400  # the timeline needs a date range

    def count(**extra):
        with CaptureQueriesContext(connection) as ctx:
            res = client.get(URL, {**params, **extra})
        assert res.status_code == 200
        return len(ctx)

    make(room, people["staff"], at(1, "09:00"), at(1, "09:30")).attendees.set([people["colleague"]])
    small, small_mine = count(), count(mine="1")
    for i in range(8):
        other = make_user(f"p{i}@test.com")
        make(room, other, at(1, "10:00") + timedelta(minutes=30 * i), at(1, "10:30") + timedelta(minutes=30 * i)).attendees.set([people["staff"], other])
    assert count() == small and count(mine="1") == small_mine
    assert len(client.get(URL, {"mine": "1"}).data) == 9


def test_seed_creates_resources_and_bookings(db):
    from django.core.management import call_command

    call_command("seed_demo", stdout=io.StringIO())
    assert Resource.objects.count() == 5
    assert Resource.objects.filter(type="vehicle", needs_approval=True).exists()
    assert Booking.objects.filter(status="pending").count() == 1 and Booking.objects.count() >= 6
    assert not Notification.objects.filter(type__in=["booking", "approval_request"]).exists()
