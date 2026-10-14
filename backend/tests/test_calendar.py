"""Shared office calendar: who adds and sees meetings, events and holidays; meeting rooms through
bookings; notifications (with preferences) and reminders; the calendar feed and the dashboard.
Also the display-preference fixes (clock setting, preferences kept out of the team activity)."""
import io
from datetime import date, datetime, timedelta

import pytest
from django.core import mail
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.bookings import services as booking_services
from apps.bookings.models import Booking, Resource
from apps.core.models import AuditLog
from apps.core.office_time import office_today, office_tz
from apps.events import services
from apps.events.models import Event
from apps.notifications.models import Notification, NotificationPreference
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db

URL = "/api/v1/events/"
CAL = "/api/v1/calendar/"


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
    return Resource.objects.create(name="Room A", type="room", capacity=6)


def at(day_offset, hhmm):
    day = office_today() + timedelta(days=day_offset)
    return datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time(), tzinfo=office_tz())


def meeting(client, start, end, **extra):
    body = {"kind": "meeting", "title": extra.pop("title", "Planning"), "start": start.isoformat(), "end": end.isoformat(), **extra}
    return client.post(URL, body, format="json")


def feed(client, first=None, last=None, **params):
    first = first or office_today()
    last = last or first + timedelta(days=6)
    res = client.get(CAL, {"from": first.isoformat(), "to": last.isoformat(), **params})
    assert res.status_code == 200, res.data
    return res.data["items"]


# ================================================================ who adds what


def test_who_adds_meetings_events_and_holidays(client_for, people, departments):
    staff, manager, admin = (client_for(people[k]) for k in ("staff", "manager", "admin"))
    sales, ops = departments["sales"].pk, departments["ops"].pk
    assert meeting(staff, at(1, "10:00"), at(1, "11:00")).status_code == 201
    event = {"kind": "event", "title": "Training", "start": at(2, "14:00").isoformat(), "end": at(2, "16:00").isoformat()}
    assert staff.post(URL, event, format="json").status_code == 403
    assert manager.post(URL, event, format="json").status_code == 403  # "everyone" is for admins
    assert manager.post(URL, {**event, "audience": "departments", "departments": [ops]}, format="json").status_code == 403
    res = manager.post(URL, {**event, "audience": "departments", "departments": [sales]}, format="json")
    assert res.status_code == 201 and res.data["department_names"] == ["Sales"]
    assert admin.post(URL, event, format="json").status_code == 201
    holiday = {"kind": "holiday", "title": "Iqbal Day", "start_date": (office_today() + timedelta(days=20)).isoformat()}
    assert manager.post(URL, holiday, format="json").status_code == 403
    res = admin.post(URL, holiday, format="json")
    assert res.status_code == 201 and res.data["all_day"] and res.data["start_date"] == res.data["end_date"] == holiday["start_date"]
    assert AuditLog.objects.filter(action=AuditLog.Action.CREATE, object_repr="Iqbal Day").exists()


def test_who_sees_and_changes_what(client_for, people, departments):
    staff, colleague, ops = (client_for(people[k]) for k in ("staff", "colleague", "ops"))
    mine = meeting(staff, at(1, "10:00"), at(1, "11:00"), attendees=[people["colleague"].pk]).data
    client_for(people["manager"]).post(URL, {"kind": "event", "title": "Sales training", "start": at(2, "14:00").isoformat(),
                                             "end": at(2, "15:00").isoformat(), "audience": "departments",
                                             "departments": [departments["sales"].pk]}, format="json")
    client_for(people["admin"]).post(URL, {"kind": "holiday", "title": "Holiday", "start_date": (office_today() + timedelta(days=3)).isoformat()}, format="json")

    def titles(client):
        return sorted(i["title"] for i in feed(client))

    assert titles(staff) == ["Holiday", "Planning", "Sales training"]
    assert titles(colleague) == ["Holiday", "Planning", "Sales training"]  # invited
    assert titles(ops) == ["Holiday"]  # not invited, not in Sales
    assert ops.get(f"{URL}{mine['id']}/").status_code == 404
    assert client_for(people["admin"]).get(f"{URL}{mine['id']}/").status_code == 200

    url = f"{URL}{mine['id']}/"
    assert colleague.patch(url, {"title": "Hijack"}, format="json").status_code == 403  # attendees don't edit
    assert client_for(people["manager"]).patch(url, {"title": "Hijack"}, format="json").status_code == 404
    assert staff.patch(url, {"title": "Renamed"}, format="json").data["title"] == "Renamed"
    assert client_for(people["admin"]).patch(url, {"location": "Lobby"}, format="json").status_code == 200
    assert AuditLog.objects.filter(action=AuditLog.Action.UPDATE, object_id=str(mine["id"])).count() == 2
    assert colleague.delete(url).status_code == 403
    assert staff.delete(url).status_code == 204


# ================================================================ meeting rooms


def test_meeting_books_its_room(client_for, people, room, django_capture_on_commit_callbacks):
    staff = client_for(people["staff"])
    with django_capture_on_commit_callbacks(execute=True):
        res = meeting(staff, at(1, "10:00"), at(1, "11:00"), room=room.pk, attendees=[people["colleague"].pk])
    assert res.status_code == 201 and res.data["room_name"] == "Room A" and res.data["room_status"] == "confirmed"
    booking = Booking.objects.get(meeting__pk=res.data["id"])
    assert (booking.start, booking.end, booking.title) == (at(1, "10:00"), at(1, "11:00"), "Planning")
    assert list(booking.attendees.all()) == [people["colleague"]]
    # One invitation (the meeting's), not a second one from the room booking.
    assert Notification.objects.filter(recipient=people["colleague"]).count() == 1

    # The room is taken: refused, and nothing is saved.
    res = meeting(client_for(people["colleague"]), at(1, "10:30"), at(1, "11:30"), title="Clash", room=room.pk)
    assert res.status_code == 400 and "room" in res.data["errors"] and not Event.objects.filter(title="Clash").exists()
    # Outside office hours with a room: the booking rules apply.
    assert meeting(staff, at(1, "07:00"), at(1, "08:00"), room=room.pk).status_code == 400

    url = f"{URL}{Event.objects.get(title='Planning').pk}/"
    assert staff.patch(url, {"start": at(1, "14:00").isoformat(), "end": at(1, "15:00").isoformat()}, format="json").status_code == 200
    booking.refresh_from_db()
    assert (booking.start, booking.end) == (at(1, "14:00"), at(1, "15:00"))  # the room moves with the meeting
    assert meeting(staff, at(1, "10:00"), at(1, "11:00"), title="Now free", room=room.pk).status_code == 201

    assert staff.patch(url, {"room": None}, format="json").data["room"] is None
    booking.refresh_from_db()
    assert booking.status == "cancelled"
    assert staff.patch(url, {"room": room.pk}, format="json").data["room_name"] == "Room A"
    new_booking = Event.objects.get(title="Planning").booking
    with django_capture_on_commit_callbacks(execute=True):
        assert staff.delete(url).status_code == 204
    new_booking.refresh_from_db()
    assert new_booking.status == "cancelled"
    assert Notification.objects.filter(recipient=people["colleague"], title__startswith="Meeting cancelled").exists()


def test_meeting_in_a_room_that_needs_approval(client_for, people, room, django_capture_on_commit_callbacks):
    room.needs_approval = True
    room.save()
    with django_capture_on_commit_callbacks(execute=True):
        res = meeting(client_for(people["staff"]), at(1, "10:00"), at(1, "11:00"), room=room.pk)
    assert res.data["room_status"] == "pending"
    assert Notification.objects.filter(type="approval_request", recipient=people["manager"]).exists()


# ================================================================ notifications and reminders


def test_invitations_changes_and_preferences(client_for, people, departments, django_capture_on_commit_callbacks):
    NotificationPreference.objects.create(user=people["colleague"], type="meeting", in_app=True, email=False)
    staff = client_for(people["staff"])
    with django_capture_on_commit_callbacks(execute=True):
        res = meeting(staff, at(1, "10:00"), at(1, "11:00"), attendees=[people["colleague"].pk, people["manager"].pk])
    invites = Notification.objects.filter(title__contains="invited you")
    assert set(invites.values_list("recipient__email", flat=True)) == {"colleague@test.com", "manager@test.com"}
    assert [m.to for m in mail.outbox] == [["manager@test.com"]]  # email follows each person's setting
    assert "2:00 pm" not in mail.outbox[0].body and "10:00 am–11:00 am" in mail.outbox[0].body

    url = f"{URL}{res.data['id']}/"
    with django_capture_on_commit_callbacks(execute=True):
        staff.patch(url, {"start": at(1, "11:00").isoformat(), "end": at(1, "12:00").isoformat(),
                          "attendees": [people["colleague"].pk, people["ops"].pk]}, format="json")
    assert Notification.objects.filter(recipient=people["colleague"], title__startswith="Meeting changed").exists()
    assert Notification.objects.filter(recipient=people["ops"], title__contains="invited you").exists()  # newly added
    assert Notification.objects.filter(recipient=people["manager"], title__startswith="Meeting cancelled").exists()  # removed
    assert not Notification.objects.filter(recipient=people["staff"]).exists()  # never about your own action

    # Office events and holidays tell their audience (in-app by default).
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        client_for(people["manager"]).post(URL, {"kind": "event", "title": "Sales lunch", "start": at(3, "13:00").isoformat(),
                                                 "end": at(3, "14:00").isoformat(), "audience": "departments",
                                                 "departments": [departments["sales"].pk]}, format="json")
        client_for(people["admin"]).post(URL, {"kind": "holiday", "title": "Eid", "start_date": (office_today() + timedelta(days=10)).isoformat(),
                                               "end_date": (office_today() + timedelta(days=12)).isoformat()}, format="json")
    lunch = set(Notification.objects.filter(title__contains="Sales lunch").values_list("recipient__email", flat=True))
    assert lunch == {"staff@test.com", "colleague@test.com"}  # Sales only, not the organizer
    eid = Notification.objects.filter(title__contains="Eid").first()
    assert Notification.objects.filter(title__contains="Eid").count() == 5 and "–" in eid.body  # everyone but the admin; a date range
    assert mail.outbox == []


def test_meeting_reminders_once_and_not_twice_for_the_room(people, room):
    now = timezone.now()
    event = Event.objects.create(kind="meeting", title="Soon", organizer=people["staff"], start=now + timedelta(minutes=10), end=now + timedelta(minutes=40))
    event.attendees.set([people["colleague"]])
    event.booking = Booking.objects.create(resource=room, title="Soon", booked_by=people["staff"], start=event.start, end=event.end)
    event.save()
    Event.objects.create(kind="holiday", title="Holiday", all_day=True, organizer=people["admin"], start=now + timedelta(minutes=5), end=now + timedelta(days=1))
    assert services.send_reminders(now) == 1
    assert set(Notification.objects.filter(title__startswith="Meeting in 15 minutes").values_list("recipient__email", flat=True)) == {
        "staff@test.com", "colleague@test.com"}
    assert services.send_reminders(now) == 0
    assert booking_services.send_reminders(now) == 0  # the room booking doesn't remind as well


# ================================================================ calendar feed and dashboard


def test_feed_layers_tasks_bookings_and_all_day_items(client_for, people, room):
    staff = client_for(people["staff"])
    due = office_today() + timedelta(days=2)
    mine = Task.objects.create(title="Send quotation", due_date=due, created_by=people["staff"])
    mine.assignees.set([people["staff"]])
    done = Task.objects.create(title="Done one", due_date=due, status="done", created_by=people["staff"])
    done.assignees.set([people["staff"]])
    other = Task.objects.create(title="Not mine", due_date=due, created_by=people["colleague"])
    other.assignees.set([people["colleague"]])
    Booking.objects.create(resource=room, title="Room for me", booked_by=people["staff"], start=at(1, "09:00"), end=at(1, "10:00"))
    meeting(staff, at(1, "10:00"), at(1, "11:00"), title="With room", room=room.pk)
    start, end = services.day_bounds(office_today() + timedelta(days=3), office_today() + timedelta(days=4))
    Event.objects.create(kind="holiday", title="Two days off", all_day=True, start=start, end=end, organizer=people["admin"])

    items = {i["title"]: i for i in feed(staff)}
    assert set(items) == {"Send quotation", "Room for me", "With room", "Two days off"}  # no duplicate for the meeting's room
    assert items["Send quotation"]["type"] == "task" and items["Send quotation"]["all_day"] and items["Send quotation"]["url"] == f"/tasks/{mine.pk}"
    assert items["With room"]["room"] == "Room A" and items["Room for me"]["type"] == "booking"
    holiday = items["Two days off"]
    assert holiday["start_date"] == (office_today() + timedelta(days=3)).isoformat() and holiday["end_date"] == (office_today() + timedelta(days=4)).isoformat()
    only = {i["type"] for i in feed(staff, layers="holidays,tasks")}
    assert only == {"holiday", "task"}
    assert staff.get(CAL, {"from": "2026-01-01", "to": "2026-06-01"}).status_code == 400


def test_feed_query_count_does_not_grow(client_for, people, make_user, room):
    staff = client_for(people["staff"])

    def count():
        with CaptureQueriesContext(connection) as ctx:
            feed(staff)
        return len(ctx)

    def add(i):
        other = make_user(f"p{i}@test.com")
        e = Event.objects.create(kind="meeting", title=f"M{i}", organizer=other, start=at(1, "09:00") + timedelta(minutes=30 * i),
                                 end=at(1, "09:30") + timedelta(minutes=30 * i))
        e.attendees.set([people["staff"], other])
        e.booking = Booking.objects.create(resource=room, title=f"M{i}", booked_by=other, start=e.start, end=e.end)
        e.save()
        t = Task.objects.create(title=f"T{i}", due_date=office_today() + timedelta(days=1), created_by=other)
        t.assignees.set([people["staff"]])

    add(0)
    small = count()
    for i in range(1, 8):
        add(i)
    assert count() == small


def test_dashboard_meetings_today(client_for, people, room):
    start, end = services.day_bounds(office_today(), office_today())
    Event.objects.create(kind="holiday", title="Holiday today", all_day=True, start=start, end=end, organizer=people["admin"])
    today = datetime.combine(office_today(), datetime.strptime("10:00", "%H:%M").time(), tzinfo=office_tz())
    mine = Event.objects.create(kind="meeting", title="My meeting", organizer=people["colleague"], start=today, end=today + timedelta(hours=1))
    mine.attendees.set([people["staff"]])
    Event.objects.create(kind="meeting", title="Not mine", organizer=people["colleague"], start=today, end=today + timedelta(hours=1))
    Booking.objects.create(resource=room, title="Room booking", booked_by=people["ops"], start=today + timedelta(hours=2), end=today + timedelta(hours=3))
    titles = [i["title"] for i in client_for(people["staff"]).get("/api/v1/dashboard/").data["meetings_today"]]
    assert titles == ["Holiday today", "My meeting", "Room booking"]


# ================================================================ display preferences (fixes)


def test_clock_setting_and_preferences_out_of_team_activity(client_for, people):
    staff = client_for(people["staff"])
    assert staff.get("/api/v1/auth/me/").data["time_format"] == ""  # follows the organization (12-hour by default)
    assert client_for(people["admin"]).get("/api/v1/settings/organization/").data["time_format"] == "12h"
    assert staff.patch("/api/v1/auth/me/", {"time_format": "24h", "theme": "dark", "language": "ur"}, format="json").status_code == 200
    staff.patch("/api/v1/auth/me/", {"job_title": "Team lead"}, format="json")
    entries = AuditLog.objects.filter(actor=people["staff"]).order_by("timestamp")
    assert [e.description for e in entries] == ["Changed display preferences", "Updated own profile"]  # both audited
    activity = client_for(people["manager"]).get("/api/v1/dashboard/").data["activity"]
    assert [a["description"] for a in activity if a["actor_name"] == people["staff"].full_name] == ["Updated own profile"]


def test_seed_creates_calendar(db):
    from django.core.management import call_command

    call_command("seed_demo", stdout=io.StringIO())
    assert Event.objects.filter(kind="holiday").count() == 2 and Event.objects.filter(kind="event").count() == 2
    assert Event.objects.filter(kind="meeting", booking__isnull=False).count() == 1
    assert all(e.start.date() >= date.today() - timedelta(days=1) for e in Event.objects.filter(kind="holiday"))
    assert not Notification.objects.filter(type__in=["meeting", "office_event"]).exists()
