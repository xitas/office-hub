"""Calendar operations: add, change and remove meetings, events and holidays; meeting rooms; reminders.

A meeting's room is a normal booking (apps.bookings): its rules (office hours, limits, approval,
no double booking) apply. The meeting sends the invitations, changes and reminders itself, so the
room booking stays quiet towards attendees (approval requests still go to the approvers).
"""
from datetime import datetime, time, timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.bookings import services as bookings
from apps.core.office_time import office_tz
from apps.notifications.models import NotificationType
from apps.notifications.services import notify

from . import rules
from .models import Event

REMINDER_LEAD = timedelta(minutes=15)


class CalendarError(ValueError):
    """{field: message} for problems with the times or the room."""

    def __init__(self, errors: dict):
        self.errors = errors
        super().__init__(next(iter(errors.values())))


def day_bounds(first, last):
    """All-day items: from the office's midnight on `first` to the midnight after `last`."""
    tz = office_tz()
    return datetime.combine(first, time.min, tzinfo=tz), datetime.combine(last + timedelta(days=1), time.min, tzinfo=tz)


def link(event) -> str:
    day = event.start.astimezone(office_tz()).date()
    return f"/calendar?date={day.isoformat()}&event={event.pk}"


def _people(event):
    return [p for p in [event.organizer, *event.attendees.all()] if p is not None]


def _params(event, actor=None) -> dict:
    return {
        "title": event.title,
        "start": event.start.isoformat(),
        "end": event.end.isoformat(),
        "all_day": event.all_day,
        "location": event.location or (event.booking.resource.name if event.booking_id else ""),
        "actor": actor.full_name if actor else "",
    }


# ================================================================ meeting rooms


def _book_room(user, event, room, attendees):
    try:
        created, _skipped = bookings.create(
            user, room, title=event.title, start=event.start, end=event.end, attendees=attendees, invite=False,
        )
    except bookings.BookingConflict as exc:
        clash = exc.booking
        raise CalendarError({"room": _("The room is already booked then: %(title)s (%(name)s)") % {
            "title": clash.title, "name": clash.booked_by.full_name,
        } if clash else str(exc)})
    except ValueError as exc:
        occurrence = exc.args[0][0] if exc.args and isinstance(exc.args[0], list) else None
        raise CalendarError({"room": occurrence.message if occurrence else str(exc)})
    return created[0]


def _room_problems(user, room, start, end):
    problems = bookings.time_problems(user, start, end)
    if problems:
        raise CalendarError({"room": next(iter(problems.values()))})
    if not bookings.rules.can_book(user, room):
        raise CalendarError({"room": _("You can't book this room.")})


# ================================================================ add, change, remove


def create(user, data: dict) -> Event:
    room = data.pop("room", None)
    attendees = [a for a in data.pop("attendees", []) if a.pk != user.pk]
    departments = data.pop("departments", [])
    with transaction.atomic():
        event = Event.objects.create(organizer=user, **data)
        event.attendees.set(attendees)
        event.departments.set(departments)
        if room is not None:
            _room_problems(user, room, event.start, event.end)
            event.booking = _book_room(user, event, room, attendees)
            event.save(update_fields=["booking"])
        pk = event.pk
        transaction.on_commit(lambda: _announce_new(pk))
    return event


def change(user, event: Event, data: dict, *, room_given=False) -> Event:
    """Update an item. For a meeting, `room_given` says whether `data["room"]` (possibly None) was sent."""
    room = data.pop("room", None)
    attendees = data.pop("attendees", None)
    departments = data.pop("departments", None)
    before = {"title": event.title, "start": event.start, "end": event.end, "location": event.location}
    old_people = {p.pk for p in event.attendees.all()}
    with transaction.atomic():
        for field, value in data.items():
            setattr(event, field, value)
        event.save()
        if attendees is not None:
            event.attendees.set([a for a in attendees if a.pk != event.organizer_id])
        if departments is not None:
            event.departments.set(departments)
        if event.kind == Event.Kind.MEETING:
            _sync_room(user, event, room if room_given else (event.booking.resource if event.booking_id else None))
        pk, actor_pk = event.pk, user.pk
        transaction.on_commit(lambda: _announce_change(pk, actor_pk, before, old_people))
    return event


def _sync_room(user, event, room):
    booking = event.booking
    if booking is not None and booking.status not in booking.HOLDING:
        booking = None  # a rejected or cancelled room booking no longer holds anything
    if room is None:
        if booking is not None:
            bookings.cancel(user, booking, announce=False)
        event.booking = None
    elif booking is not None and booking.resource_id == room.pk:
        changes = {}
        if (booking.start, booking.end) != (event.start, event.end):
            changes.update(start=event.start, end=event.end)
        if booking.title != event.title:
            changes["title"] = event.title
        changes["attendees"] = list(event.attendees.all())
        try:
            bookings.change(user, booking, changes, announce=False)
        except bookings.BookingConflict as exc:
            clash = exc.booking
            raise CalendarError({"room": _("The room is already booked then: %(title)s (%(name)s)") % {
                "title": clash.title, "name": clash.booked_by.full_name,
            } if clash else str(exc)})
        except ValueError as exc:
            raise CalendarError({"room": str(exc)})
    else:
        if booking is not None:
            bookings.cancel(user, booking, announce=False)
        _room_problems(user, room, event.start, event.end)
        event.booking = _book_room(user, event, room, list(event.attendees.all()))
    event.save(update_fields=["booking"])


def remove(user, event: Event):
    """Delete an item; a meeting's room booking is cancelled and its people are told."""
    with transaction.atomic():
        if event.booking_id and event.booking.status in event.booking.HOLDING and not event.booking.is_past:
            bookings.cancel(user, event.booking, announce=False)
        people = _people(event) if event.kind == Event.Kind.MEETING and event.end > timezone.now() else []
        params = _params(event, user)
        event.delete()
        if people:
            transaction.on_commit(lambda: notify(people, NotificationType.MEETING, link="/calendar", actor=user,
                                                 message="meeting_cancelled", params=params))


# ================================================================ notifications


def _announce_new(pk):
    event = Event.objects.select_related("organizer", "booking__resource").get(pk=pk)
    actor = event.organizer
    if event.kind == Event.Kind.MEETING:
        notify(list(event.attendees.all()), NotificationType.MEETING, link=link(event), actor=actor,
               message="meeting_invite", params=_params(event, actor))
    else:
        notify(list(rules.audience_users(event)), NotificationType.OFFICE_EVENT, link=link(event), actor=actor,
               message="holiday_added" if event.kind == Event.Kind.HOLIDAY else "event_added", params=_params(event, actor))


def _announce_change(pk, actor_pk, before, old_people):
    from apps.accounts.models import User

    event = Event.objects.select_related("organizer", "booking__resource").get(pk=pk)
    if event.kind != Event.Kind.MEETING or event.end <= timezone.now():
        return
    actor = User.objects.get(pk=actor_pk)
    people = _people(event)
    new = [p for p in event.attendees.all() if p.pk not in old_people]
    removed = list(User.objects.filter(pk__in=old_people - {p.pk for p in event.attendees.all()}))
    changed = (before["title"], before["start"], before["end"], before["location"]) != (event.title, event.start, event.end, event.location)
    if changed:
        notify([p for p in people if p not in new], NotificationType.MEETING, link=link(event), actor=actor,
               message="meeting_changed", params=_params(event, actor))
    if new:
        notify(new, NotificationType.MEETING, link=link(event), actor=actor, message="meeting_invite", params=_params(event, actor))
    if removed:
        notify(removed, NotificationType.MEETING, link="/calendar", actor=actor, message="meeting_cancelled", params=_params(event, actor))


def send_reminders(now=None) -> int:
    """Meetings starting within 15 minutes: remind the organizer and attendees, once per start time."""
    now = now or timezone.now()
    due = (
        Event.objects.filter(kind=Event.Kind.MEETING, all_day=False, start__gt=now, start__lte=now + REMINDER_LEAD)
        .select_related("organizer", "booking__resource")
        .prefetch_related("attendees")
    )
    sent = 0
    for event in due:
        if event.reminded_start == event.start:
            continue
        claimed = Event.objects.filter(pk=event.pk).exclude(reminded_start=event.start).update(reminded_start=event.start)
        if not claimed:
            continue  # another run got there first
        notify(_people(event), NotificationType.MEETING, link=link(event), message="meeting_reminder", params=_params(event))
        sent += 1
    return sent
