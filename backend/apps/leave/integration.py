"""Dashboard "Pending approvals": leave and booking requests waiting for my decision (oldest first)."""
from django.utils import translation
from django.utils.translation import gettext as _

from apps.bookings import rules as booking_rules
from apps.bookings.models import Booking
from apps.core.office_time import office_tz
from apps.dashboard import registry as dashboard

from . import rules
from .models import LeaveRequest


def type_name(leave_type) -> str:
    """The leave type's Urdu name in Urdu (when it has one)."""
    return leave_type.name_ur if leave_type.name_ur and (translation.get_language() or "").startswith("ur") else leave_type.name


def leave_dates(req) -> str:
    if req.start_date == req.end_date:
        return req.start_date.strftime("%d/%m/%Y")
    return f"{req.start_date:%d/%m}–{req.end_date:%d/%m/%Y}"


def pending_approvals(user, limit=8):
    leave = list(
        rules.decidable_requests(user).select_related("user", "leave_type").order_by("created_at")[:limit]
    )
    items = [
        {
            "id": f"leave:{r.pk}",
            "title": r.user.full_name,
            "subtitle": f"{type_name(r.leave_type)} · {leave_dates(r)} · " + (_("%(n)s days") % {"n": f"{r.days.normalize():f}"}),
            "badge": _("Leave"),
            "time": None,
            "url": "/leave?tab=team",
        }
        for r in leave
    ]
    bookings = (
        booking_rules.decidable_bookings(user).filter(status=Booking.Status.PENDING)
        .select_related("booked_by", "resource").order_by("created_at")[:limit]
    )
    tz = office_tz()
    items += [
        {
            "id": f"booking:{b.pk}",
            "title": b.booked_by.full_name,
            "subtitle": f"{b.resource.name} · {b.start.astimezone(tz):%d/%m/%Y}",
            "badge": _("Booking"),
            "time": b.start.isoformat(),
            "end": b.end.isoformat(),
            "url": "/bookings/mine?tab=approvals",
        }
        for b in bookings
    ]
    return items[:limit]


def register():
    dashboard.register("pending_approvals", pending_approvals)
