"""Checking in and out at field visits, and what happens to the location afterwards.

- Location is taken only at check-in and check-out (the browser asks then, never in the background), and only
  when the person allows it. Declining, or a device that can't tell, still checks in: marked "no location".
- Checking in starts the day's attendance as "on a field visit" when the person hasn't checked in yet
  (attendance's own check-in), so the attendance overview shows them out on a visit.
- Whoever planned the visit for someone else hears when they arrive and leave. The person going is reminded once
  if a planned visit started 30 minutes ago and they haven't checked in.
- Exact coordinates are removed after 90 days (a daily job, one audit entry per run); times and visits stay.
"""
import math
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_noop as N_

from apps.core.audit import log_action
from apps.core.models import AuditLog
from apps.notifications.models import NotificationType
from apps.notifications.services import notify

from . import rules
from .models import Visit, VisitCheck
from .services import VisitError, _load, _params, link

KEEP_LOCATION = timedelta(days=90)
MISSED_AFTER = timedelta(minutes=30)
EARTH_RADIUS_M = 6_371_000


def distance_m(lat1, lng1, lat2, lng2) -> int:
    """Great-circle distance in metres (haversine)."""
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp, dl = p2 - p1, math.radians(float(lng2) - float(lng1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * EARTH_RADIUS_M * math.asin(math.sqrt(a)))


def _place(location: dict) -> dict:
    """Validated location fields: recorded (with coordinates, accuracy if known), declined or unavailable."""
    status = location.get("location")
    if status == VisitCheck.Location.RECORDED:
        lat, lng = location.get("latitude"), location.get("longitude")
        if lat is None or lng is None:
            raise VisitError({"latitude": _("A recorded location needs latitude and longitude.")})
        accuracy = location.get("accuracy")
        return {"location": status, "latitude": Decimal(lat).quantize(Decimal("0.000001")),
                "longitude": Decimal(lng).quantize(Decimal("0.000001")), "accuracy": round(accuracy) if accuracy is not None else None}
    return {"location": status, "latitude": None, "longitude": None, "accuracy": None}


def check_in(user, visit, location: dict, now=None) -> VisitCheck:
    now = now or timezone.now()
    if not rules.can_check_in(user, visit, now):
        raise PermissionError
    place = _place(location)
    try:
        with transaction.atomic():
            check = VisitCheck.objects.create(
                visit=visit, user=user, checked_in_at=now, in_location=place["location"], in_latitude=place["latitude"],
                in_longitude=place["longitude"], in_accuracy=place["accuracy"],
            )
    except IntegrityError:
        raise VisitError({"detail": _("You have already checked in at this visit.")})
    _start_field_day(user, visit, now)
    pk, user_pk = visit.pk, user.pk
    transaction.on_commit(lambda: _tell_planner(pk, user_pk, "visit_checked_in"))
    return check


def check_out(user, visit, location: dict, now=None) -> VisitCheck:
    now = now or timezone.now()
    check = VisitCheck.objects.filter(visit=visit, user=user).first()
    if check is None:
        raise VisitError({"detail": _("Check in first.")})
    if check.checked_out_at:
        raise VisitError({"detail": _("You have already checked out of this visit.")})
    place = _place(location)
    check.checked_out_at, check.out_location = now, place["location"]
    check.out_latitude, check.out_longitude, check.out_accuracy = place["latitude"], place["longitude"], place["accuracy"]
    check.save(update_fields=["checked_out_at", "out_location", "out_latitude", "out_longitude", "out_accuracy"])
    pk, user_pk = visit.pk, user.pk
    transaction.on_commit(lambda: _tell_planner(pk, user_pk, "visit_checked_out"))
    return check


def _start_field_day(user, visit, now):
    """Attendance: the day starts "on a field visit" if the person hasn't checked in yet (otherwise it's left as is)."""
    from apps.attendance import services as attendance
    from apps.attendance.models import Attendance
    from apps.core.permissions import has_perm

    if not has_perm(user, "attendance", "create"):
        return
    try:
        attendance.check_in(user, Attendance.Mode.FIELD, _("Visit: %(title)s") % {"title": visit.title}, now=now)
    except attendance.AttendanceError:
        pass  # already checked in today (in the office or at an earlier visit)


def _tell_planner(pk, user_pk, message):
    """Whoever planned the visit for someone else hears they arrived (or left), at what time."""
    from apps.accounts.models import User

    visit, person = _load(pk), User.objects.get(pk=user_pk)
    if not visit.created_by or visit.created_by_id == person.pk:
        return
    check = VisitCheck.objects.get(visit=visit, user=person)
    at = check.checked_out_at if message == "visit_checked_out" else check.checked_in_at
    notify(visit.created_by, NotificationType.VISIT, link=link(visit), actor=person, message=message,
           params={**_params(visit, person), "person": person.full_name, "at": at.isoformat()})


def send_missed_check_in(now=None) -> int:
    """Planned visits that started 30+ minutes ago (and haven't ended) with no check-in from the person responsible:
    remind them once per start time."""
    now = now or timezone.now()
    due = (
        Visit.objects.filter(status=Visit.Status.PLANNED, start__lte=now - MISSED_AFTER, end__gt=now)
        .exclude(checks__user_id=F("assigned_to_id"))
        .select_related("assigned_to", "contact", "company", "vendor")
    )
    sent = 0
    for visit in due:
        if visit.check_in_reminded_start == visit.start:
            continue
        if not Visit.objects.filter(pk=visit.pk).exclude(check_in_reminded_start=visit.start).update(check_in_reminded_start=visit.start):
            continue
        notify(visit.assigned_to, NotificationType.VISIT, link=link(visit), message="visit_check_in_missed", params=_params(visit))
        sent += 1
    return sent


def remove_old_locations(now=None) -> int:
    """Clear check-in and check-out coordinates older than 90 days; one audit entry for the whole run."""
    now = now or timezone.now()
    cutoff = now - KEEP_LOCATION
    old = VisitCheck.objects.filter(checked_in_at__lt=cutoff, location_removed_at__isnull=True).exclude(
        in_latitude__isnull=True, out_latitude__isnull=True
    )
    count = old.update(in_latitude=None, in_longitude=None, in_accuracy=None, out_latitude=None, out_longitude=None,
                       out_accuracy=None, location_removed_at=now)
    if count:
        log_action(None, AuditLog.Action.UPDATE, changes={"check_ins": count, "older_than": cutoff.isoformat()},
                   description=N_("Removed visit locations older than 90 days"), object_repr=f"{count} visit check-ins")
    return count
