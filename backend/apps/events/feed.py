"""One list for the calendar: meetings, office events and holidays, plus my task deadlines, my
bookings (made by me or with me; a meeting's room booking shows as the meeting), team leave and my
field visits. Fixed number of queries whatever the range holds."""
from datetime import date, datetime, time, timedelta

from django.db.models import Count, Q

from apps.bookings.models import Booking
from apps.core.office_time import office_tz
from apps.tasks.models import Task

from . import rules
from .models import Event

LAYERS = ("meetings", "events", "holidays", "tasks", "bookings", "leave", "visits")
MAX_DAYS = 62


def _local_day(moment):
    return moment.astimezone(office_tz()).date()


def _event_item(e, user) -> dict:
    item = {
        "key": f"event:{e.pk}",
        "type": e.kind,
        "id": e.pk,
        "title": e.title,
        "start": e.start.isoformat(),
        "end": e.end.isoformat(),
        "all_day": e.all_day,
        "location": e.location,
        "room": e.booking.resource.name if e.booking_id and e.booking.status in Booking.HOLDING else None,
        "room_status": e.booking.status if e.booking_id else None,
        "organizer": e.organizer.full_name if e.organizer else None,
        "attendee_count": e.attendee_count,
        "can_edit": rules.can_manage(user, e),
        "url": None,
    }
    if e.all_day:
        item["start_date"] = _local_day(e.start).isoformat()
        item["end_date"] = (_local_day(e.end) - timedelta(days=1)).isoformat()
    return item


def _task_item(t, today) -> dict:
    timed = t.due_time is not None
    tz = office_tz()
    start = datetime.combine(t.due_date, t.due_time or time.min, tzinfo=tz)
    return {
        "key": f"task:{t.pk}",
        "type": "task",
        "id": t.pk,
        "title": t.title,
        "start": start.isoformat(),
        "end": (start + timedelta(minutes=30 if timed else 24 * 60)).isoformat(),
        "all_day": not timed,
        "start_date": t.due_date.isoformat(),
        "end_date": t.due_date.isoformat(),
        "priority": t.priority,
        "status": t.status,
        "is_overdue": t.due_date < today,
        "url": f"/tasks/{t.pk}",
    }


def _booking_item(b) -> dict:
    return {
        "key": f"booking:{b.pk}",
        "type": "booking",
        "id": b.pk,
        "title": b.title,
        "start": b.start.isoformat(),
        "end": b.end.isoformat(),
        "all_day": False,
        "room": b.resource.name,
        "room_status": b.status,
        "organizer": b.booked_by.full_name,
        "url": f"/bookings?date={_local_day(b.start).isoformat()}&booking={b.pk}",
    }


def calendar_items(user, first: date, last: date, layers=LAYERS, today: date | None = None) -> list[dict]:
    tz = office_tz()
    start = datetime.combine(first, time.min, tzinfo=tz)
    end = datetime.combine(last + timedelta(days=1), time.min, tzinfo=tz)
    today = today or datetime.now(tz).date()
    items = []
    kinds = [k for k, layer in ((Event.Kind.MEETING, "meetings"), (Event.Kind.EVENT, "events"), (Event.Kind.HOLIDAY, "holidays")) if layer in layers]
    if kinds:
        events = (
            rules.visible_events(user)
            .filter(kind__in=kinds, start__lt=end, end__gt=start)
            .select_related("organizer", "booking__resource")
            .annotate(attendee_count=Count("attendees", distinct=True))
        )
        if rules.is_admin(user):
            # Admins may open any meeting, but their calendar shows only the meetings they're part of.
            invited = Event.attendees.through.objects.filter(user_id=user.pk).values("event_id")
            events = events.filter(~Q(kind=Event.Kind.MEETING) | Q(organizer=user) | Q(pk__in=invited))
        items += [_event_item(e, user) for e in events]
    if "tasks" in layers:
        tasks = (
            Task.objects.filter(assignees=user, due_date__gte=first, due_date__lte=last)
            .exclude(status=Task.Status.DONE)
            .only("pk", "title", "due_date", "due_time", "priority", "status")
        )
        items += [_task_item(t, today) for t in tasks]
    if "bookings" in layers:
        invited = Booking.attendees.through.objects.filter(user_id=user.pk).values("booking_id")
        mine = (
            Booking.objects.filter(Q(booked_by=user) | Q(pk__in=invited), status__in=Booking.HOLDING, start__lt=end, end__gt=start)
            .filter(meeting__isnull=True)
            .select_related("resource", "booked_by")
        )
        items += [_booking_item(b) for b in mine]
    if "leave" in layers:
        from apps.leave import rules as leave_rules
        from apps.leave.integration import type_name

        away = (
            leave_rules.department_leave(user).filter(start_date__lte=last, end_date__gte=first)
            .select_related("user", "leave_type")
        )
        for r in away:
            s, e = datetime.combine(r.start_date, time.min, tzinfo=tz), datetime.combine(r.end_date + timedelta(days=1), time.min, tzinfo=tz)
            items.append({
                "key": f"leave:{r.pk}", "type": "leave", "id": r.pk, "title": r.user.full_name, "subtitle": type_name(r.leave_type),
                "start": s.isoformat(), "end": e.isoformat(), "all_day": True, "half_day": r.half_day,
                "start_date": r.start_date.isoformat(), "end_date": r.end_date.isoformat(), "url": "/leave?tab=team",
            })
    if "visits" in layers:
        from apps.core.permissions import has_perm

        if has_perm(user, "visits", "view"):
            from apps.visits.integration import calendar_items as visit_items

            items += visit_items(user, start, end)
    items.sort(key=lambda i: (not i["all_day"], i["start"], i["title"]))
    return items
