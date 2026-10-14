"""Dashboard: "Today's meetings and bookings" = today's holiday, my meetings, and the office's bookings."""
from datetime import datetime, time, timedelta

from django.db.models import Q
from django.utils.translation import gettext as _

from apps.bookings.integration import bookings_for_meetings_widget
from apps.bookings.models import Booking
from apps.core.office_time import office_today, office_tz
from apps.dashboard import registry as dashboard

from . import services
from .models import Event


def meetings_today(user, limit=8):
    tz = office_tz()
    today = office_today()
    start, end = datetime.combine(today, time.min, tzinfo=tz), datetime.combine(today + timedelta(days=1), time.min, tzinfo=tz)
    invited = Event.attendees.through.objects.filter(user_id=user.pk).values("event_id")
    events = (
        Event.objects.filter(start__lt=end, end__gt=start)
        .filter(Q(kind=Event.Kind.HOLIDAY) | Q(kind=Event.Kind.MEETING) & (Q(organizer=user) | Q(pk__in=invited)))
        .select_related("organizer", "booking__resource")
        .order_by("-all_day", "start")
    )
    items = []
    for e in events[:limit]:
        holiday = e.kind == Event.Kind.HOLIDAY
        room = e.booking.resource.name if e.booking_id and e.booking.status in Booking.HOLDING else ""
        place = room or e.location
        items.append({
            "id": f"event:{e.pk}",
            "title": e.title,
            "subtitle": _("Office holiday") if holiday else " · ".join(p for p in (place, e.organizer.full_name if e.organizer else "") if p),
            "time": None if e.all_day else e.start.isoformat(),
            "end": None if e.all_day else e.end.isoformat(),
            "badge": _("Room waiting for approval") if e.booking_id and e.booking.status == Booking.Status.PENDING else None,
            "url": services.link(e),
        })
    return (items + bookings_for_meetings_widget(user, limit))[:limit]


def register():
    dashboard.register("meetings_today", meetings_today)
