"""Dashboard widgets for bookings (registered in BookingsConfig.ready())."""
from datetime import datetime, time, timedelta

from django.db.models import Q
from django.utils.translation import gettext as _

from apps.core.office_time import office_today, office_tz
from apps.dashboard import registry as dashboard

from . import rules, services
from .models import Booking, Resource


def _today_range():
    tz = office_tz()
    today = office_today()
    return datetime.combine(today, time.min, tzinfo=tz), datetime.combine(today + timedelta(days=1), time.min, tzinfo=tz)


def _item(booking, *, mine: bool) -> dict:
    pending = booking.status == Booking.Status.PENDING
    subtitle = booking.resource.name if mine else f"{booking.resource.name} · {booking.booked_by.full_name}"
    return {
        "id": booking.pk,
        "title": booking.title,
        "subtitle": subtitle,
        "time": booking.start.isoformat(),
        "end": booking.end.isoformat(),
        "badge": _("Pending approval") if pending else None,
        "url": services.link(booking),
    }


def my_bookings_today(user, limit=8):
    """My bookings today (made by me or with me), confirmed or waiting for approval."""
    start, end = _today_range()
    qs = (
        Booking.objects.filter(Q(booked_by=user) | Q(pk__in=Booking.attendees.through.objects.filter(user=user).values("booking_id")))
        .filter(start__lt=end, end__gt=start, status__in=Booking.HOLDING)
        .select_related("resource", "booked_by")
        .order_by("start", "id")
    )
    return [_item(b, mine=True) for b in qs[:limit]]


def meetings_today(user, limit=8):
    """Today's confirmed bookings across the resources I can see: rooms first (meetings), then the rest."""
    start, end = _today_range()
    qs = (
        Booking.objects.filter(resource__in=rules.visible_resources(user), start__lt=end, end__gt=start, status=Booking.Status.CONFIRMED)
        .select_related("resource", "booked_by")
        .order_by("start", "id")
    )
    items = list(qs[:limit * 2])
    items.sort(key=lambda b: (b.resource.type != Resource.Type.ROOM, b.start))
    return [_item(b, mine=False) for b in items[:limit]]


def register():
    dashboard.register("bookings_today", my_bookings_today)
    dashboard.register("meetings_today", meetings_today)
