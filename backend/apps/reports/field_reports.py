"""Field reports: visits completed vs. planned, and errands done and not done.

Visits scheduled in the period (by start, office time; approved ones: planned, done or cancelled, not pending or
rejected), for the person responsible: done, cancelled, not closed (past their end and still planned), upcoming,
completion rate (done out of those whose time has come: done, cancelled and not closed), how many the person
checked in at, and how many have a report, with the reports' outcomes. By person, purpose and outcome.

Errands due in the period (undated ones by when they were asked for), for their runner (waiting ones under
"nobody yet"): done, not done, cancelled, still open, overdue, done by the due time, and the success rate (done out of
done or not done). By person and kind.

Every visit has one person responsible and every errand at most one runner, so the totals are the sum of the
per-person rows. All counting is grouped in the database (a fixed number of queries).
"""
from datetime import datetime

from django.db.models import Count, F, Q
from django.utils import timezone

from apps.errands import rules as errand_rules
from apps.errands.models import Errand
from apps.visits.models import Visit, VisitCheck, VisitReport

from .scope import day_bounds

SCHEDULED = (Visit.Status.PLANNED, Visit.Status.DONE, Visit.Status.CANCELLED)
PURPOSES = [p for p, _label in Visit.Purpose.choices]
OUTCOMES = [o for o, _label in VisitReport.Outcome.choices]
KINDS = [k for k, _label in Errand.Kind.choices]


def _rate(part, whole):
    return round(part / whole, 4) if whole else None


# ================================================================ visits


VISIT_EMPTY = {"scheduled": 0, "done": 0, "cancelled": 0, "not_closed": 0, "upcoming": 0, "checked_in": 0, "reported": 0}


def _visit_counts(now: datetime):
    return {
        "scheduled": Count("pk"),
        "done": Count("pk", filter=Q(status=Visit.Status.DONE)),
        "cancelled": Count("pk", filter=Q(status=Visit.Status.CANCELLED)),
        "not_closed": Count("pk", filter=Q(status=Visit.Status.PLANNED, end__lt=now)),
        "upcoming": Count("pk", filter=Q(status=Visit.Status.PLANNED, end__gte=now)),
        "reported": Count("pk", filter=Q(report__isnull=False)),
    }


def _visit_rates(row: dict) -> dict:
    due = row["done"] + row["cancelled"] + row["not_closed"]
    return {**row, "completion": _rate(row["done"], due), "check_in_rate": _rate(row["checked_in"], row["done"]),
            "report_rate": _rate(row["reported"], row["done"])}


def visits(user, scope, first, last) -> dict:
    """By person, purpose and outcome (5 queries). A report's people are always within what the viewer may see
    (visible_visits: a manager's department, everyone for admins), so visits are filtered by the person responsible
    directly, without the visibility subquery."""
    start, end = day_bounds(first, last)
    now = timezone.now()
    people_ids = [p.pk for p in scope.people]
    qs = Visit.objects.filter(assigned_to_id__in=people_ids, start__gte=start, start__lt=end, status__in=SCHEDULED)
    counts = _visit_counts(now)
    by_person = {r.pop("assigned_to_id"): {**VISIT_EMPTY, **r} for r in qs.values("assigned_to_id").annotate(**counts).order_by()}
    by_purpose = {r.pop("purpose"): {**VISIT_EMPTY, **r} for r in qs.values("purpose").annotate(**counts).order_by()}
    # Checked in: the person responsible checked in at the visit (companions' check-ins aside).
    checks = VisitCheck.objects.filter(visit__in=qs, user_id=F("visit__assigned_to_id"))
    for r in checks.values("visit__assigned_to_id").annotate(n=Count("visit_id", distinct=True)).order_by():
        by_person.setdefault(r["visit__assigned_to_id"], dict(VISIT_EMPTY))["checked_in"] = r["n"]
    for r in checks.values("visit__purpose").annotate(n=Count("visit_id", distinct=True)).order_by():
        by_purpose.setdefault(r["visit__purpose"], dict(VISIT_EMPTY))["checked_in"] = r["n"]
    outcomes = dict(VisitReport.objects.filter(visit__in=qs).values_list("outcome").annotate(n=Count("pk")).order_by())
    totals = {k: sum(r[k] for r in by_person.values()) for k in VISIT_EMPTY}
    reported = sum(outcomes.values())
    return {
        "from": first, "to": last,
        "people": [_visit_rates({"id": p.pk, "name": p.full_name, "department": p.department.name if p.department else None,
                                 **by_person.get(p.pk, VISIT_EMPTY)}) for p in scope.people],
        "purposes": [_visit_rates({"purpose": k, **by_purpose.get(k, VISIT_EMPTY)}) for k in PURPOSES],
        "outcomes": [{"outcome": o, "count": outcomes.get(o, 0), "share": _rate(outcomes.get(o, 0), reported)} for o in OUTCOMES],
        "totals": _visit_rates(totals),
    }


# ================================================================ errands


ERRAND_EMPTY = {"asked": 0, "done": 0, "failed": 0, "cancelled": 0, "open": 0, "overdue": 0, "on_time": 0}


def _errand_counts(now: datetime):
    active = [Errand.Status.OPEN, Errand.Status.ASSIGNED, Errand.Status.ON_THE_WAY]
    return {
        "asked": Count("pk"),
        "done": Count("pk", filter=Q(status=Errand.Status.DONE)),
        "failed": Count("pk", filter=Q(status=Errand.Status.FAILED)),
        "cancelled": Count("pk", filter=Q(status=Errand.Status.CANCELLED)),
        "open": Count("pk", filter=Q(status__in=active)),
        "overdue": Count("pk", filter=Q(status__in=active, due_at__lt=now)),
        "on_time": Count("pk", filter=Q(status=Errand.Status.DONE, due_at__isnull=False, finished_at__lte=F("due_at"))),
    }


def _errand_rates(row: dict) -> dict:
    return {**row, "success": _rate(row["done"], row["done"] + row["failed"]), "on_time_rate": _rate(row["on_time"], row["done"])}


def errands(user, scope, first, last) -> dict:
    """By runner (waiting ones under "nobody yet") and kind (3 queries). Errands are scoped with visible_errands()
    (it filters by the errand's department, which an admin's assignment can differ from) and then to the runners in
    the report; waiting errands count when they belong to the report's department (admins: any)."""
    start, end = day_bounds(first, last)
    now = timezone.now()
    people_ids = [p.pk for p in scope.people]
    in_period = Q(due_at__gte=start, due_at__lt=end) | Q(due_at__isnull=True, created_at__gte=start, created_at__lt=end)
    whose = Q(assigned_to_id__in=people_ids)
    if scope.person is None:
        waiting = Q(assigned_to__isnull=True)
        if scope.department is not None:
            waiting &= Q(department_id=scope.department.pk)
        whose |= waiting
    qs = errand_rules.visible_errands(user).filter(in_period, whose)
    counts = _errand_counts(now)
    by_person = {r.pop("assigned_to_id"): {**ERRAND_EMPTY, **r} for r in qs.values("assigned_to_id").annotate(**counts).order_by()}
    by_kind = {r.pop("kind"): {**ERRAND_EMPTY, **r} for r in qs.values("kind").annotate(**counts).order_by()}
    people = [_errand_rates({"id": p.pk, "name": p.full_name, "department": p.department.name if p.department else None,
                             **by_person.get(p.pk, ERRAND_EMPTY)}) for p in scope.people]
    if None in by_person:
        people.append(_errand_rates({"id": None, "name": None, "department": None, **by_person[None]}))
    return {
        "from": first, "to": last, "people": people,
        "kinds": [_errand_rates({"kind": k, **by_kind.get(k, ERRAND_EMPTY)}) for k in KINDS],
        "totals": _errand_rates({k: sum(r[k] for r in by_person.values()) for k in ERRAND_EMPTY}),
    }
