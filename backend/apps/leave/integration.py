"""Dashboard "Pending approvals": leave and booking requests join the combined approvals query."""
from django.db.models import F
from django.utils import translation
from django.utils.translation import gettext as _

from apps.bookings import rules as booking_rules
from apps.bookings.models import Booking
from apps.core.office_time import office_tz
from apps.dashboard import approvals
from apps.dashboard import registry as dashboard

from . import rules


def type_name(leave_type) -> str:
    """The leave type's Urdu name in Urdu (when it has one)."""
    return leave_type.name_ur if leave_type.name_ur and (translation.get_language() or "").startswith("ur") else leave_type.name


def leave_dates(req) -> str:
    if req.start_date == req.end_date:
        return req.start_date.strftime("%d/%m/%Y")
    return f"{req.start_date:%d/%m}–{req.end_date:%d/%m/%Y}"


def _leave_rows(user):
    return approvals.columns(
        rules.decidable_requests(user), "leave",
        a_created=F("created_at"), a_name=F("user__full_name"), a_label=F("leave_type__name"),
        a_label_ur=F("leave_type__name_ur"), a_first=F("start_date"), a_last=F("end_date"), a_number=F("days"),
        a_extra=F("half_day"),
    )


def _leave_item(r) -> dict:
    urdu = (translation.get_language() or "").startswith("ur")
    kind = r["a_label_ur"] if urdu and r["a_label_ur"] else r["a_label"]
    first, last = r["a_first"], r["a_last"]
    when = f"{first:%d/%m/%Y}" if first == last else f"{first:%d/%m}–{last:%d/%m/%Y}"
    return {
        "id": f"leave:{r['a_id']}",
        "title": r["a_name"],
        "subtitle": f"{kind} · {when} · " + (_("%(n)s days") % {"n": f"{r['a_number'].normalize():f}"}),
        "badge": _("Leave"),
        "time": None,
        "url": "/leave?tab=team",
    }


def _booking_rows(user):
    return approvals.columns(
        booking_rules.decidable_bookings(user).filter(status=Booking.Status.PENDING), "booking",
        a_created=F("created_at"), a_name=F("booked_by__full_name"), a_label=F("resource__name"),
        a_start=F("start"), a_end=F("end"),
    )


def _booking_item(r) -> dict:
    return {
        "id": f"booking:{r['a_id']}",
        "title": r["a_name"],
        "subtitle": f"{r['a_label']} · {r['a_start'].astimezone(office_tz()):%d/%m/%Y}",
        "badge": _("Booking"),
        "time": r["a_start"].isoformat(),
        "end": r["a_end"].isoformat(),
        "url": "/bookings/mine?tab=approvals",
    }


def register():
    approvals.register("leave", _leave_rows, _leave_item)
    approvals.register("booking", _booking_rows, _booking_item)
    dashboard.register("pending_approvals", approvals.pending)
