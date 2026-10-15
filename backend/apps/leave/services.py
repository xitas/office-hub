"""Leave days, balances, requests and decisions (used by the API, the seed command and tests)."""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models import OrganizationSettings
from apps.core.office_time import office_today, office_tz
from apps.notifications.models import NotificationType
from apps.notifications.services import notify

from . import rules
from .models import LeaveBalance, LeaveRequest, LeaveType

HALF = Decimal("0.5")
ONE = Decimal("1")


class LeaveError(ValueError):
    """{field: message}"""

    def __init__(self, errors: dict):
        self.errors = errors
        super().__init__(next(iter(errors.values())))


# ================================================================ counting days


@dataclass
class DayCount:
    days: Decimal
    skipped: list[dict] = field(default_factory=list)  # [{"date", "reason": "weekend"|"holiday", "title"}]


def holidays_between(first: date, last: date) -> dict[date, str]:
    """Office holidays (calendar) on each day of the range: {day: title}."""
    from apps.events.models import Event

    tz = office_tz()
    out = {}
    for h in Event.objects.filter(kind=Event.Kind.HOLIDAY, start__lt=_midnight(last + timedelta(days=1)), end__gt=_midnight(first)):
        day = max(h.start.astimezone(tz).date(), first)
        until = min((h.end.astimezone(tz) - timedelta(seconds=1)).date(), last)
        while day <= until:
            out.setdefault(day, h.title)
            day += timedelta(days=1)
    return out


def _midnight(day: date):
    from datetime import datetime, time

    return datetime.combine(day, time.min, tzinfo=office_tz())


def count_days(first: date, last: date, half_day: str = "") -> DayCount:
    """Working days from first to last (inclusive) that aren't office holidays; a half day counts 0.5."""
    working = set(OrganizationSettings.cached().working_days)
    holidays = holidays_between(first, last)
    total, skipped = Decimal("0"), []
    day = first
    while day <= last:
        if day.weekday() not in working:
            skipped.append({"date": day.isoformat(), "reason": "weekend", "title": ""})
        elif day in holidays:
            skipped.append({"date": day.isoformat(), "reason": "holiday", "title": holidays[day]})
        else:
            total += ONE
        day += timedelta(days=1)
    if half_day and total:
        total = HALF
    return DayCount(total, skipped)


# ================================================================ balances


def balance_for(user, leave_type, year) -> LeaveBalance:
    """The person's balance row for a type and year (made from the type's days the first time)."""
    balance, _created = LeaveBalance.objects.get_or_create(
        user=user, leave_type=leave_type, year=year, defaults={"allowance": leave_type.days_per_year or Decimal("0")}
    )
    return balance


def used_days(user_ids, year) -> dict[tuple[int, int], dict[str, Decimal]]:
    """{(user id, type id): {"used": approved days, "pending": pending days}} for a year, in one query."""
    rows = (
        LeaveRequest.objects.filter(user_id__in=user_ids, start_date__year=year, status__in=LeaveRequest.HOLDING)
        .values("user_id", "leave_type_id", "status")
        .annotate(days=Sum("days"))
    )
    out: dict = {}
    for r in rows:
        entry = out.setdefault((r["user_id"], r["leave_type_id"]), {"used": Decimal("0"), "pending": Decimal("0")})
        entry["used" if r["status"] == LeaveRequest.Status.APPROVED else "pending"] += r["days"]
    return out


def summaries(users, year) -> list[dict]:
    """Balances of several people for every active type (fixed number of queries)."""
    users = list(users)
    types = list(LeaveType.objects.filter(is_active=True))
    stored = {
        (b.user_id, b.leave_type_id): b
        for b in LeaveBalance.objects.filter(user__in=users, year=year, leave_type__in=types)
    }
    usage = used_days([u.pk for u in users], year)
    out = []
    for u in users:
        for t in types:
            balance = stored.get((u.pk, t.pk))
            limited = t.days_per_year is not None
            allowance = balance.allowance if balance else (t.days_per_year or Decimal("0"))
            use = usage.get((u.pk, t.pk), {"used": Decimal("0"), "pending": Decimal("0")})
            out.append({
                "id": balance.pk if balance else None,
                "user": u.pk,
                "user_name": u.full_name,
                "leave_type": t.pk,
                "year": year,
                "limited": limited,
                "allowance": allowance if limited else None,
                "used": use["used"],
                "pending": use["pending"],
                "remaining": (allowance - use["used"] - use["pending"]) if limited else None,
                "note": balance.note if balance else "",
            })
    return out


# ================================================================ requests


def _check(user, leave_type, first, last, half_day, *, exclude=None) -> DayCount:
    if last < first:
        raise LeaveError({"end_date": _("The last day can't be before the first.")})
    if first.year != last.year:
        raise LeaveError({"end_date": _("Leave can't run into the next year. Make two requests, one for each year.")})
    if not office_today().year <= first.year <= office_today().year + 1:
        raise LeaveError({"start_date": _("This year's or next year's leave only.")})
    if half_day:
        if not leave_type.allow_half_days:
            raise LeaveError({"half_day": _("This type of leave is taken in whole days.")})
        if first != last:
            raise LeaveError({"half_day": _("A half day is a single day.")})
    if not leave_type.is_active:
        raise LeaveError({"leave_type": _("This type of leave can't be requested any more.")})
    count = count_days(first, last, half_day)
    if not count.days:
        raise LeaveError({"start_date": _("Those dates are all weekends or office holidays.")})
    overlapping = LeaveRequest.objects.filter(user=user, status__in=LeaveRequest.HOLDING, start_date__lte=last, end_date__gte=first)
    if exclude is not None:
        overlapping = overlapping.exclude(pk=exclude.pk)
    if overlapping.exists():
        raise LeaveError({"start_date": _("You already have leave on some of these days.")})
    if leave_type.days_per_year is not None:
        summary = next(s for s in summaries([user], first.year) if s["leave_type"] == leave_type.pk)
        if count.days > summary["remaining"]:
            raise LeaveError({"leave_type": _("Not enough %(type)s left: %(left)s days remaining.") % {
                "type": leave_type.name, "left": _fmt(summary["remaining"]),
            }})
    return count


def _fmt(days: Decimal) -> str:
    return f"{days.normalize():f}" if days else "0"


def preview(user, leave_type, first, last, half_day="") -> dict:
    """What a request would count (without saving): days, skipped weekends/holidays, and the balance after."""
    count = count_days(first, last, half_day) if last >= first else DayCount(Decimal("0"))
    remaining = None
    if leave_type.days_per_year is not None:
        remaining = next(s for s in summaries([user], first.year) if s["leave_type"] == leave_type.pk)["remaining"]
    problem = ""
    try:
        _check(user, leave_type, first, last, half_day)
    except LeaveError as exc:
        problem = str(exc)
    return {"days": count.days, "skipped": count.skipped, "remaining": remaining,
            "remaining_after": (remaining - count.days) if remaining is not None else None, "problem": problem}


def request_leave(user, leave_type, first, last, half_day="", reason="") -> LeaveRequest:
    with transaction.atomic():
        # One request at a time per person, so two quick submissions can't both spend the same days.
        type(user).objects.select_for_update().filter(pk=user.pk).first()
        count = _check(user, leave_type, first, last, half_day)
        auto = rules.is_admin(user)
        req = LeaveRequest.objects.create(
            user=user, leave_type=leave_type, start_date=first, end_date=last, half_day=half_day, days=count.days,
            reason=reason.strip(), status=LeaveRequest.Status.APPROVED if auto else LeaveRequest.Status.PENDING,
            decided_by=user if auto else None, decided_at=timezone.now() if auto else None,
        )
        if not auto:
            pk = req.pk
            transaction.on_commit(lambda: _announce_request(pk))
    return req


def decide(user, req, *, approve: bool, note: str = "") -> LeaveRequest:
    if not rules.can_decide(user, req):
        raise PermissionError
    with transaction.atomic():
        type(user).objects.select_for_update().filter(pk=req.user_id).first()
        if approve and req.leave_type.days_per_year is not None:
            # Other requests may have been approved meanwhile: this one still has to fit.
            summary = next(s for s in summaries([req.user], req.start_date.year) if s["leave_type"] == req.leave_type_id)
            if summary["remaining"] < 0:
                raise LeaveError({"detail": _("Not enough %(type)s left to approve this.") % {"type": req.leave_type.name}})
        req.status = LeaveRequest.Status.APPROVED if approve else LeaveRequest.Status.REJECTED
        req.decided_by, req.decided_at, req.decision_note = user, timezone.now(), note.strip()[:300]
        req.save(update_fields=["status", "decided_by", "decided_at", "decision_note", "updated_at"])
        pk = req.pk
        transaction.on_commit(lambda: _announce_decision(pk))
    return req


def cancel(user, req) -> LeaveRequest:
    if not rules.can_cancel(user, req, office_today()):
        raise PermissionError
    was_approved = req.status == LeaveRequest.Status.APPROVED
    req.status = LeaveRequest.Status.CANCELLED
    req.cancelled_by, req.cancelled_at = user, timezone.now()
    req.save(update_fields=["status", "cancelled_by", "cancelled_at", "updated_at"])
    pk, actor_pk = req.pk, user.pk
    transaction.on_commit(lambda: _announce_cancel(pk, actor_pk, was_approved))
    return req


# ================================================================ notifications


def _params(req, actor=None) -> dict:
    return {
        "name": req.user.full_name,
        "type": req.leave_type.name,
        "type_ur": req.leave_type.name_ur,
        "start": req.start_date.isoformat(),
        "end": req.end_date.isoformat(),
        "days": _fmt(req.days),
        "half_day": req.half_day,
        "actor": actor.full_name if actor else "",
        "note": req.decision_note,
    }


def _announce_request(pk):
    req = LeaveRequest.objects.select_related("user", "leave_type").get(pk=pk)
    notify(rules.approvers_for(req.user), NotificationType.APPROVAL_REQUEST, link="/leave?tab=team", actor=req.user,
           message="leave_request", params=_params(req, req.user))


def _announce_decision(pk):
    req = LeaveRequest.objects.select_related("user", "leave_type", "decided_by").get(pk=pk)
    notify(req.user, NotificationType.APPROVAL_RESULT, link="/leave", actor=req.decided_by,
           message="leave_approved" if req.status == LeaveRequest.Status.APPROVED else "leave_rejected",
           params=_params(req, req.decided_by))


def _announce_cancel(pk, actor_pk, was_approved):
    from apps.accounts.models import User

    req = LeaveRequest.objects.select_related("user", "leave_type").get(pk=pk)
    actor = User.objects.get(pk=actor_pk)
    if actor.pk == req.user_id:
        # The requester withdrew it: whoever approves (or approved) it is told.
        people = [req.decided_by] if was_approved and req.decided_by_id else rules.approvers_for(req.user)
    else:
        people = [req.user]
    notify([p for p in people if p], NotificationType.APPROVAL_RESULT, link="/leave?tab=team" if actor.pk == req.user_id else "/leave",
           actor=actor, message="leave_cancelled", params=_params(req, actor))
