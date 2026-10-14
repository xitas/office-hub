"""Booking rules and operations (used by the API, the seed command, the reminder job and tests).

Rules for every booking (admins are exempt only from the length and "how far ahead" limits):
- 15-minute slots: start and end on :00, :15, :30 or :45, at least 15 minutes long, on one day;
- within office hours (Organization page), in the office time zone;
- not in the past, at most `booking_max_minutes` long, at most `booking_horizon_days` ahead;
- no overlap with a confirmed or pending booking of the same resource.

Overlaps are checked while holding a lock on the resource row, so two requests for the same
resource are handled one after the other. PostgreSQL also refuses overlaps with an exclusion
constraint; if one slips through anyway (it can't with the lock), the IntegrityError becomes the
same "already booked" answer.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models import OrganizationSettings
from apps.core.office_time import clock, office_tz
from apps.notifications.models import NotificationType
from apps.notifications.services import notify
from apps.tasks import recurrence

from . import rules
from .models import Booking, BookingSeries, Resource

SLOT = timedelta(minutes=15)
REMINDER_LEAD = timedelta(minutes=15)
MAX_OCCURRENCES = 100


class BookingConflict(Exception):
    """The resource is already booked for (part of) that time."""

    def __init__(self, booking=None):
        self.booking = booking
        super().__init__(_("This time is already booked."))


# ================================================================ time rules


def floor_slot(moment: datetime) -> datetime:
    local = moment.astimezone(office_tz())
    return local.replace(minute=local.minute - local.minute % 15, second=0, microsecond=0)


def time_problems(user, start: datetime, end: datetime, *, now=None) -> dict[str, str]:
    """{field: message} for every rule the times break (empty when fine)."""
    org = OrganizationSettings.cached()
    tz = office_tz()
    now = now or timezone.now()
    s, e = start.astimezone(tz), end.astimezone(tz)
    problems = {}
    if e <= s:
        return {"end": _("The end must be after the start.")}
    if any(t.minute % 15 or t.second or t.microsecond for t in (s, e)):
        problems["start"] = _("Use 15-minute steps (e.g. 10:00, 10:15, 10:30).")
    if s.date() != e.date():
        problems["end"] = _("A booking must start and end on the same day.")
    elif s.time() < org.office_opens or e.time() > org.office_closes:
        problems["start"] = _("Bookings must be within office hours (%(opens)s–%(closes)s).") % {
            "opens": clock(org.office_opens), "closes": clock(org.office_closes),
        }
    if start < floor_slot(now):
        problems["start"] = _("This time has already passed.")
    if not rules.is_admin(user):
        if end - start > timedelta(minutes=org.booking_max_minutes):
            hours, minutes = divmod(org.booking_max_minutes, 60)
            problems["end"] = _("A booking can be at most %(length)s long.") % {
                "length": f"{hours}:{minutes:02d}" if minutes else _("%(n)s hours") % {"n": hours}
            }
        if s.date() > now.astimezone(tz).date() + timedelta(days=org.booking_horizon_days):
            problems["start"] = _("You can book at most %(days)s days ahead.") % {"days": org.booking_horizon_days}
    return problems


def overlapping(resource, start, end, *, exclude=None):
    qs = Booking.objects.filter(resource=resource, status__in=Booking.HOLDING, start__lt=end, end__gt=start)
    if exclude is not None:
        qs = qs.exclude(pk=exclude.pk)
    return qs.select_related("booked_by")


# ================================================================ repeats


@dataclass
class Occurrence:
    start: datetime
    end: datetime
    problem: str | None = None  # "conflict" | "rules"
    message: str = ""
    conflict: Booking | None = None


def occurrence_times(start: datetime, end: datetime, weekdays: list[int], until: date) -> list[tuple[datetime, datetime]]:
    """The first booking and every later weekday in the list, up to and including `until` (same clock times)."""
    tz = office_tz()
    s, e = start.astimezone(tz), end.astimezone(tz)
    rule = recurrence.Rule(recurrence.WEEKLY, start=s.date(), weekdays=sorted(set(weekdays)), end_date=until)
    days = [s.date()]
    d = rule.next_after(s.date())
    while d is not None and len(days) < MAX_OCCURRENCES:
        days.append(d)
        d = rule.next_after(d)
    return [
        (datetime.combine(day, s.time(), tzinfo=tz), datetime.combine(day, e.time(), tzinfo=tz)) for day in days
    ]


def check_occurrences(user, resource, times, *, exclude=None) -> list[Occurrence]:
    result = []
    for start, end in times:
        occ = Occurrence(start, end)
        problems = time_problems(user, start, end)
        if problems:
            occ.problem, occ.message = "rules", next(iter(problems.values()))
        else:
            clash = overlapping(resource, start, end, exclude=exclude).first()
            if clash:
                occ.problem, occ.conflict = "conflict", clash
                occ.message = _("Already booked: %(title)s (%(name)s)") % {"title": clash.title, "name": clash.booked_by.full_name}
        result.append(occ)
    return result


# ================================================================ create, change, cancel


def _lock(resource):
    # Serializes bookings of one resource (PostgreSQL; SQLite locks the whole database for writes anyway).
    Resource.objects.select_for_update().filter(pk=resource.pk).first()


def create(user, resource, *, title, start, end, attendees=(), notes="", repeat=None, skip_conflicts=False, invite=True):
    """Book one time, or a weekly series. Returns (bookings, skipped occurrences).

    Raises BookingConflict when the (only) time is taken, or ValueError(occurrences) when a series
    has problems and `skip_conflicts` is off.
    """
    status = Booking.Status.PENDING if resource.needs_approval and not rules.is_admin(user) else Booking.Status.CONFIRMED
    times = occurrence_times(start, end, repeat["weekdays"], repeat["until"]) if repeat else [(start, end)]
    attendees = [a for a in attendees if a.pk != user.pk]
    with transaction.atomic():
        _lock(resource)
        occurrences = check_occurrences(user, resource, times)
        bad = [o for o in occurrences if o.problem]
        if not repeat and bad:
            if bad[0].problem == "conflict":
                raise BookingConflict(bad[0].conflict)
            raise ValueError(occurrences)
        if bad and not skip_conflicts:
            raise ValueError(occurrences)
        good = [o for o in occurrences if not o.problem]
        if not good:
            raise ValueError(occurrences)
        series = BookingSeries.objects.create(weekdays=repeat["weekdays"], until=repeat["until"], created_by=user) if repeat else None
        created = []
        try:
            with transaction.atomic():
                for o in good:
                    booking = Booking.objects.create(
                        resource=resource, title=title, start=o.start, end=o.end, booked_by=user, notes=notes,
                        status=status, series=series,
                    )
                    booking.attendees.set(attendees)
                    created.append(booking)
        except IntegrityError:
            raise BookingConflict()
        # `invite=False`: a meeting books its room and sends its own invitations (approval requests still go out).
        transaction.on_commit(lambda: _announce_new(created, user, invite=invite))
    return created, bad


def change(user, booking, data: dict, *, announce=True) -> Booking:
    """Edit title, notes, attendees, resource or times. New times are checked again; on a resource
    that needs approval, a non-admin's new time goes back to "pending"."""
    if booking.status not in Booking.HOLDING or booking.is_past:
        raise ValueError(_("Only upcoming bookings can be changed."))
    resource = data.get("resource", booking.resource)
    start, end = data.get("start", booking.start), data.get("end", booking.end)
    moved = resource != booking.resource or start != booking.start or end != booking.end
    before = {"title": booking.title, "start": booking.start, "end": booking.end, "resource": booking.resource_id}
    old_attendees = set(booking.attendees.values_list("pk", flat=True))
    with transaction.atomic():
        if moved:
            if resource != booking.resource and not rules.can_book(user, resource):
                raise ValueError(_("You can't book this resource."))
            problems = time_problems(user, start, end)
            if problems:
                raise ValueError(next(iter(problems.values())))
            _lock(resource)
            clash = overlapping(resource, start, end, exclude=booking).first()
            if clash:
                raise BookingConflict(clash)
            booking.resource, booking.start, booking.end = resource, start, end
            if resource.needs_approval and not rules.is_admin(user):
                booking.status = Booking.Status.PENDING
                booking.decided_by, booking.decided_at, booking.decision_reason = None, None, ""
        for field in ("title", "notes"):
            if field in data:
                setattr(booking, field, data[field])
        try:
            with transaction.atomic():
                booking.save()
        except IntegrityError:
            raise BookingConflict()
        if "attendees" in data:
            booking.attendees.set([a for a in data["attendees"] if a.pk != booking.booked_by_id])
        pk, actor_pk = booking.pk, user.pk
        if announce:
            transaction.on_commit(lambda: _announce_change(pk, actor_pk, before, old_attendees))
    return booking


def cancel(user, booking, *, following=False, announce=True) -> list[Booking]:
    """Cancel this booking (and, with `following`, the later ones of its series)."""
    targets = [booking]
    if following and booking.series_id:
        targets = list(
            Booking.objects.filter(series_id=booking.series_id, start__gte=booking.start, status__in=Booking.HOLDING)
            .select_related("resource", "booked_by")
        )
    targets = [b for b in targets if b.status in Booking.HOLDING and not b.is_past]
    if not targets:
        raise ValueError(_("Only upcoming bookings can be cancelled."))
    now = timezone.now()
    Booking.objects.filter(pk__in=[b.pk for b in targets]).update(
        status=Booking.Status.CANCELLED, cancelled_by=user, cancelled_at=now, updated_at=now
    )
    ids, actor_pk = [b.pk for b in targets], user.pk
    if announce:
        transaction.on_commit(lambda: _announce_cancel(ids, actor_pk))
    return targets


def decide(user, booking, *, approve: bool, reason: str = "") -> Booking:
    if not rules.can_decide(user, booking):
        raise PermissionError
    booking.status = Booking.Status.CONFIRMED if approve else Booking.Status.REJECTED
    booking.decided_by, booking.decided_at, booking.decision_reason = user, timezone.now(), reason.strip()[:300]
    booking.save(update_fields=["status", "decided_by", "decided_at", "decision_reason", "updated_at"])
    pk = booking.pk
    transaction.on_commit(lambda: _announce_decision(pk))
    return booking


# ================================================================ notifications


def _params(booking, actor=None, **extra) -> dict:
    return {
        "title": booking.title,
        "resource": booking.resource.name,
        "start": booking.start.isoformat(),
        "end": booking.end.isoformat(),
        "actor": actor.full_name if actor else "",
        **extra,
    }


def link(booking) -> str:
    day = booking.start.astimezone(office_tz()).date()
    return f"/bookings?date={day.isoformat()}&booking={booking.pk}"


def _announce_new(bookings, user, invite=True):
    first = bookings[0]
    extra = {"more": len(bookings) - 1}
    if first.status == Booking.Status.PENDING:
        notify(
            rules.approvers_for(user), NotificationType.APPROVAL_REQUEST, link="/bookings/mine?tab=approvals",
            actor=user, message="booking_request", params=_params(first, user, **extra),
        )
    elif invite:
        notify(
            list(first.attendees.all()), NotificationType.BOOKING, link=link(first), actor=user,
            message="booking_invited", params=_params(first, user, **extra),
        )


def _people(booking):
    return [booking.booked_by, *booking.attendees.all()]


def _announce_change(pk, actor_pk, before, old_attendees):
    from apps.accounts.models import User

    booking = Booking.objects.select_related("resource", "booked_by").get(pk=pk)
    actor = User.objects.get(pk=actor_pk)
    people = _people(booking)
    new = [p for p in booking.attendees.all() if p.pk not in old_attendees]
    changed = before["start"] != booking.start or before["end"] != booking.end or before["resource"] != booking.resource_id or before["title"] != booking.title
    if changed:
        notify([p for p in people if p not in new], NotificationType.BOOKING, link=link(booking), actor=actor,
               message="booking_changed", params=_params(booking, actor))
    if new:
        notify(new, NotificationType.BOOKING, link=link(booking), actor=actor, message="booking_invited", params=_params(booking, actor))
    if booking.status == Booking.Status.PENDING and changed:
        notify(rules.approvers_for(booking.booked_by), NotificationType.APPROVAL_REQUEST, link="/bookings/mine?tab=approvals",
               actor=actor, message="booking_request", params=_params(booking, actor, more=0))


def _announce_cancel(ids, actor_pk):
    from apps.accounts.models import User

    actor = User.objects.get(pk=actor_pk)
    bookings = list(Booking.objects.filter(pk__in=ids).select_related("resource", "booked_by").prefetch_related("attendees").order_by("start"))
    if not bookings:
        return
    first = bookings[0]
    notify(_people(first), NotificationType.BOOKING, link=link(first), actor=actor, message="booking_cancelled",
           params=_params(first, actor, more=len(bookings) - 1))


def _announce_decision(pk):
    booking = Booking.objects.select_related("resource", "booked_by", "decided_by").get(pk=pk)
    approved = booking.status == Booking.Status.CONFIRMED
    notify(
        booking.booked_by, NotificationType.APPROVAL_RESULT, link=link(booking), actor=booking.decided_by,
        message="booking_approved" if approved else "booking_rejected",
        params=_params(booking, booking.decided_by, reason=booking.decision_reason),
    )
    if approved and not hasattr(booking, "meeting"):  # a meeting's people were invited by the meeting
        notify(list(booking.attendees.all()), NotificationType.BOOKING, link=link(booking), actor=booking.booked_by,
               message="booking_invited", params=_params(booking, booking.booked_by, more=0))


# ================================================================ reminders


def send_reminders(now=None) -> int:
    """Confirmed bookings starting within 15 minutes: remind the booker and attendees, once per start time.

    The claim is a conditional update (only if this start time wasn't reminded yet), so overlapping
    runs never remind twice; a booking moved to a new time gets a new reminder.
    """
    now = now or timezone.now()
    due = (
        # A meeting's room booking is left out: the meeting reminds its organizer and attendees.
        Booking.objects.filter(status=Booking.Status.CONFIRMED, start__gt=now, start__lte=now + REMINDER_LEAD, meeting__isnull=True)
        .select_related("resource", "booked_by")
        .prefetch_related("attendees")
    )
    sent = 0
    for booking in due:
        if booking.reminded_start == booking.start:
            continue
        claimed = Booking.objects.filter(pk=booking.pk).exclude(reminded_start=booking.start).update(reminded_start=booking.start)
        if not claimed:
            continue
        notify(_people(booking), NotificationType.BOOKING, link=link(booking), message="booking_reminder", params=_params(booking))
        sent += 1
    return sent
