"""Attendance and leave summary for a period: days in the office, on field visits, working remotely, late, on leave
and absent, per person, department and overall; leave taken by type, and the year's balances.

Days follow the attendance page's rules (apps.attendance.status), counted over working days (the office's working
week, office holidays left out) up to today, from the day each person joined:
- in the office / field / remote: days checked in, in that mode (any day, also days off); late: office and remote
  check-ins after the office opened plus the grace minutes;
- on leave: working days with approved leave and no check-in (someone on half-day leave who checked in is present);
- absent: past working days with no check-in and no leave (today isn't absent yet), counted from the day the person
  joined (or first checked in, if earlier);
- attendance rate: working days checked in out of those plus the absent days.

Leave taken: approved leave on working days in the period (days still to come included), half days as 0.5; waiting:
requests not yet decided. Balances are for the year the period ends in, as on the leave page.

Check-ins are counted in the database (grouped, whatever the number of days); leave requests are few and are spread
over their days here. A fixed number of queries.
"""
from bisect import bisect_left
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, Min, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce, TruncTime
from django.db.models.lookups import GreaterThan

from apps.attendance.models import Attendance
from apps.core.models import OrganizationSettings
from apps.core.office_time import office_today, office_tz
from apps.leave.models import LeaveRequest, LeaveType
from apps.leave.services import holidays_between, summaries

DAY_KEYS = ("working_days", "office", "field", "remote", "late", "leave", "absent", "attended")
HALF = Decimal("0.5")


def _rate(part, whole):
    return round(part / whole, 4) if whole else None


def _with_rate(row: dict) -> dict:
    return {**row, "rate": _rate(row["attended"], row["attended"] + row["absent"])}


def _django_week_days(working) -> list[int]:
    """Python weekdays (Monday 0) as Django's __week_day values (Sunday 1 … Saturday 7)."""
    return [(d + 1) % 7 + 1 for d in working]


def _late_after() -> time:
    org = OrganizationSettings.cached()
    moment = datetime.combine(date(2000, 1, 1), org.office_opens) + timedelta(minutes=org.late_after_minutes)
    return moment.time() if moment.date() == date(2000, 1, 1) else time.max


def _num(value: Decimal) -> float | int:
    return int(value) if value == value.to_integral_value() else float(value)


def summary(user, scope, first: date, last: date) -> dict:
    tz, today = office_tz(), office_today()
    org = OrganizationSettings.cached()
    working = set(org.working_days)
    holidays = holidays_between(first, last)
    people_ids = [p.pk for p in scope.people]

    # Working days of the period, and those up to today (sorted, to count each person's from the day they joined).
    days, day = [], first
    while day <= last:
        if day.weekday() in working and day not in holidays:
            days.append(day)
        day += timedelta(days=1)
    upto_today = [d for d in days if d <= today]

    workday = Q(date__week_day__in=_django_week_days(working)) & ~Q(date__in=list(holidays))
    checked = Attendance.objects.filter(user_id__in=people_ids, date__gte=first, date__lte=min(last, today), check_in__isnull=False)
    late = GreaterThan(TruncTime("check_in", tzinfo=tz), _late_after())
    by_person = {
        r.pop("user_id"): r
        for r in checked.values("user_id").annotate(
            office=Count("pk", filter=Q(mode=Attendance.Mode.OFFICE)),
            field=Count("pk", filter=Q(mode=Attendance.Mode.FIELD)),
            remote=Count("pk", filter=Q(mode=Attendance.Mode.REMOTE)),
            late=Count("pk", filter=Q(late, ~Q(mode=Attendance.Mode.FIELD))),
            attended=Count("pk", filter=workday),
            today=Count("pk", filter=Q(date=today)),
        ).order_by()
    }
    # Each person's days start when they joined, or first checked in if that was earlier (records filled in later).
    first_in = dict(Attendance.objects.filter(user_id__in=people_ids, check_in__isnull=False).values("user_id")
                    .annotate(d=Min("date")).values_list("user_id", "d").order_by())

    # Leave: each request's working days in the period (half days 0.5).
    in_period = set(days)
    taken: dict[tuple[int, int], Decimal] = {}
    waiting: dict[int, Decimal] = {}
    leave_days_so_far: dict[int, int] = {}
    leave_today: set[int] = set()
    # With each request, its check-ins on working days so far (half days): present, not on leave. Counted per request
    # on the (person, date) index; a join of check-ins to requests got a poor plan (0.3–0.8 s for a year of 50 people).
    checked_on_leave: dict[int, int] = {}
    on_its_days = (checked.filter(workday, user_id=OuterRef("user_id"), date__gte=OuterRef("start_date"), date__lte=OuterRef("end_date"))
                   .values("user_id").annotate(n=Count("pk")).values("n").order_by())
    requests = LeaveRequest.objects.filter(user_id__in=people_ids, status__in=LeaveRequest.HOLDING, start_date__lte=last, end_date__gte=first)
    for r in requests.values("user_id", "leave_type_id", "status", "start_date", "end_date", "half_day").annotate(
            checked=Coalesce(Subquery(on_its_days), 0)).order_by():
        day, n = max(r["start_date"], first), Decimal("0")
        approved = r["status"] == LeaveRequest.Status.APPROVED
        while day <= min(r["end_date"], last):
            if day in in_period:
                n += HALF if r["half_day"] else 1
                if approved and day <= today:
                    leave_days_so_far[r["user_id"]] = leave_days_so_far.get(r["user_id"], 0) + 1
                    if day == today:
                        leave_today.add(r["user_id"])
            day += timedelta(days=1)
        if approved:
            checked_on_leave[r["user_id"]] = checked_on_leave.get(r["user_id"], 0) + r["checked"]
            key = (r["user_id"], r["leave_type_id"])
            taken[key] = taken.get(key, Decimal("0")) + n
        else:
            waiting[r["user_id"]] = waiting.get(r["user_id"], Decimal("0")) + n

    types = list(LeaveType.objects.filter(Q(is_active=True) | Q(pk__in={t for (_u, t) in taken})).order_by("position", "name"))
    year = last.year
    balances: dict[tuple[int, int], dict] = {(b["user"], b["leave_type"]): b for b in summaries(scope.people, year)}

    people, leave_rows = [], []
    for p in scope.people:
        joined = p.date_joined.astimezone(tz).date()
        joined = max(first, min(joined, first_in.get(p.pk, joined)))
        working_days = len(upto_today) - bisect_left(upto_today, joined)
        r = by_person.get(p.pk, {})
        attended = r.get("attended", 0)
        leave = leave_days_so_far.get(p.pk, 0) - checked_on_leave.get(p.pk, 0)
        not_in_yet = int(today in in_period and today >= joined and not r.get("today") and p.pk not in leave_today)
        row = {"working_days": working_days, "office": r.get("office", 0), "field": r.get("field", 0), "remote": r.get("remote", 0),
               "late": r.get("late", 0), "leave": leave, "attended": attended,
               "absent": max(0, working_days - attended - leave - not_in_yet)}
        people.append(_with_rate({"id": p.pk, "name": p.full_name, "department_id": p.department_id,
                                  "department": p.department.name if p.department else None, **row}))
        by_type = {t.pk: _num(taken.get((p.pk, t.pk), Decimal("0"))) for t in types}
        leave_rows.append({
            "id": p.pk, "name": p.full_name, "taken": by_type, "total": _num(sum((taken.get((p.pk, t.pk), Decimal("0")) for t in types), Decimal("0"))),
            "waiting": _num(waiting.get(p.pk, Decimal("0"))),
            "remaining": {t.pk: (None if (b := balances.get((p.pk, t.pk))) is None or b["remaining"] is None else _num(b["remaining"])) for t in types},
        })

    departments: dict = {}
    for row in people:
        d = departments.setdefault(row["department_id"], {"id": row["department_id"], "name": row["department"], "people": 0, **{k: 0 for k in DAY_KEYS}})
        d["people"] += 1
        for k in DAY_KEYS:
            d[k] += row[k]
    totals = {k: sum(r[k] for r in people) for k in DAY_KEYS}
    return {
        "from": first, "to": last, "as_of": min(last, today), "year": year,
        "period_working_days": len(days), "holidays": sum(1 for d in holidays if first <= d <= last),
        "people": people,
        "departments": [_with_rate(d) for d in sorted(departments.values(), key=lambda d: (d["name"] is None, d["name"] or ""))],
        "totals": _with_rate({**totals, "people": len(people)}),
        "leave_types": [{"id": t.pk, "name": t.name, "name_ur": t.name_ur, "limited": t.days_per_year is not None,
                         "taken": _num(sum((taken.get((p, t.pk), Decimal("0")) for p in people_ids), Decimal("0"))),
                         "people": sum(1 for p in people_ids if taken.get((p, t.pk))),
                         "allowance": _num(sum((b["allowance"] or 0 for (u, tid), b in balances.items() if tid == t.pk), Decimal("0")))
                         if t.days_per_year is not None else None,
                         "remaining": _num(sum((b["remaining"] or 0 for (u, tid), b in balances.items() if tid == t.pk), Decimal("0")))
                         if t.days_per_year is not None else None}
                        for t in types],
        "leave": leave_rows,
        "leave_totals": {"total": _num(sum(taken.values(), Decimal("0"))), "waiting": _num(sum(waiting.values(), Decimal("0")))},
    }
