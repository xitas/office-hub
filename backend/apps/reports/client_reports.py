"""Client reports: interactions per week or month, and lead pipeline conversion.

Interactions are what counts as being in touch with a client (the same kinds as "Last contacted"): calls, meetings,
emails, WhatsApp messages and visit reports logged on contacts and companies the viewer can see, by the people the
report covers. Notes are internal and not counted. They're counted per office day in the database (a year is at most
366 days × 5 kinds of rows, whatever the number of entries) and summed into weeks (from the office's week start) or
months here.

The pipeline follows leads created in the period (by when they were added, office time): how many reached
"Contacted", "In discussion", and where they stand now (won, lost, still open), from their status history; win rate
is won out of those closed (won or lost). Status changes in the period are counted from → to, and leads won in the
period with the average days from being added to being won. Leads are counted for the person they're assigned to.
"""
from datetime import date, timedelta

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q
from django.db.models.functions import TruncDate

from apps.contacts.models import Contact, ContactStatusChange
from apps.contacts.visibility import visible_companies, visible_contacts
from apps.core.models import OrganizationSettings
from apps.core.office_time import office_tz
from apps.timeline.builtin import CONTACT_KINDS
from apps.timeline.models import TimelineEntry

from .scope import day_bounds

KINDS = list(CONTACT_KINDS)
STATUSES = [s for s, _label in Contact.Status.choices]
REACHED = {  # a lead "reached" a stage if any of its status changes went to one of these
    "contacted": ["contacted", "in_discussion", "won"],
    "in_discussion": ["in_discussion", "won"],
}


def _rate(part, whole):
    return round(part / whole, 4) if whole else None


# ================================================================ interactions


def week_start(d: date, office_week_start: int) -> date:
    """The office week (0 = Sunday … 6 = Saturday, as in OrganizationSettings) that `d` falls in."""
    js_day = (d.weekday() + 1) % 7
    return d - timedelta(days=(js_day - office_week_start) % 7)


def buckets_for(first: date, last: date, by: str) -> list[tuple[date, date]]:
    """Every week or month the period touches, as (first day, last day) clipped to the period."""
    out = []
    if by == "month":
        cursor = first.replace(day=1)
        while cursor <= last:
            following = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
            out.append((max(cursor, first), min(following - timedelta(days=1), last)))
            cursor = following
        return out
    ws = OrganizationSettings.cached().week_start
    cursor = week_start(first, ws)
    while cursor <= last:
        out.append((max(cursor, first), min(cursor + timedelta(days=6), last)))
        cursor += timedelta(days=7)
    return out


def interactions(user, scope, first, last, by="week") -> dict:
    """Per week or month and kind, and per person (with how many different clients they reached): 4 queries."""
    start, end = day_bounds(first, last)
    people_ids = [p.pk for p in scope.people]
    entries = TimelineEntry.objects.filter(
        Q(contact__in=visible_contacts(user)) | Q(company__in=visible_companies(user)),
        kind__in=KINDS, occurred_at__gte=start, occurred_at__lt=end, created_by_id__in=people_ids,
    )
    per_day = (entries.annotate(day=TruncDate("occurred_at", tzinfo=office_tz())).values("day", "kind")
               .annotate(n=Count("pk")).order_by())
    spans = buckets_for(first, last, by)
    rows = [{"from": a, "to": b, "counts": dict.fromkeys(KINDS, 0)} for a, b in spans]
    for r in per_day:
        for row in rows:
            if row["from"] <= r["day"] <= row["to"]:
                row["counts"][r["kind"]] += r["n"]
                break
    for row in rows:
        row["total"] = sum(row["counts"].values())
    by_person = {}
    for r in entries.values("created_by_id", "kind").annotate(n=Count("pk")).order_by():
        by_person.setdefault(r["created_by_id"], dict.fromkeys(KINDS, 0))[r["kind"]] = r["n"]
    reached = {r["created_by_id"]: r for r in entries.values("created_by_id").annotate(
        contacts=Count("contact_id", distinct=True), companies=Count("company_id", distinct=True)).order_by()}
    totals = entries.aggregate(contacts=Count("contact_id", distinct=True), companies=Count("company_id", distinct=True))
    counts = dict.fromkeys(KINDS, 0)
    for row in rows:
        for k in KINDS:
            counts[k] += row["counts"][k]
    people = []
    for p in scope.people:
        c = by_person.get(p.pk, dict.fromkeys(KINDS, 0))
        r = reached.get(p.pk, {"contacts": 0, "companies": 0})
        people.append({"id": p.pk, "name": p.full_name, "department": p.department.name if p.department else None,
                       "counts": c, "total": sum(c.values()), "clients": r["contacts"] + r["companies"]})
    return {
        "from": first, "to": last, "by": by, "kinds": KINDS, "buckets": rows, "people": people,
        "totals": {"counts": counts, "total": sum(counts.values()), "clients": totals["contacts"] + totals["companies"]},
    }


# ================================================================ pipeline


def _lead_q(scope, prefix=""):
    """Leads assigned to the people in the report (admins' "everyone": unassigned ones too), as a filter on the lead
    itself or, with a prefix such as "contact__", through a join. A report's people are always ones whose leads the
    viewer may see (a manager's own department; admins everyone), so this stays within visible_contacts() without
    its subquery, which made the status-change counts take over a second for a year of data."""
    q = Q(**{f"{prefix}assigned_to_id__in": [p.pk for p in scope.people]})
    if scope.department is None and scope.person is None:
        q |= Q(**{f"{prefix}assigned_to__isnull": True})
    return q


def _leads(user, scope):
    """Contacts the viewer can see, assigned to the people in the report."""
    return visible_contacts(user).filter(_lead_q(scope))


def _outcome_counts():
    return {
        "created": Count("pk"),
        "won": Count("pk", filter=Q(status="won")),
        "lost": Count("pk", filter=Q(status="lost")),
        "open": Count("pk", filter=Q(status__in=["new", "contacted", "in_discussion"])),
    }


def _with_rates(row: dict) -> dict:
    closed = row["won"] + row["lost"]
    return {**row, "win_rate": _rate(row["won"], closed), "conversion": _rate(row["won"], row["created"])}


EMPTY_FUNNEL = {"created": 0, "contacted": 0, "in_discussion": 0, "won": 0, "lost": 0, "open": 0}


def pipeline(user, scope, first, last) -> dict:
    """Leads added in the period and how far they got; status changes and wins in the period (5 queries).

    Each lead has one assignee (or none), so the overall funnel is the sum of the per-person rows. How far a lead got
    is counted from its status changes in one grouped query (not a lookup per lead, which took seconds for a year).
    """
    start, end = day_bounds(first, last)
    leads = _leads(user, scope)
    cohort = leads.filter(created_at__gte=start, created_at__lt=end)
    rows = {r.pop("assigned_to_id"): {**EMPTY_FUNNEL, **r} for r in cohort.values("assigned_to_id").annotate(**_outcome_counts()).order_by()}
    reached = ContactStatusChange.objects.filter(contact_id__in=cohort.values("pk")).values("contact__assigned_to_id").annotate(**{
        stage: Count("contact_id", distinct=True, filter=Q(to_status__in=to)) for stage, to in REACHED.items()
    }).order_by()
    for r in reached:
        rows.setdefault(r.pop("contact__assigned_to_id"), dict(EMPTY_FUNNEL)).update(r)
    by_person = rows
    totals = _with_rates({k: sum(r[k] for r in rows.values()) for k in EMPTY_FUNNEL})
    changes = ContactStatusChange.objects.filter(_lead_q(scope, "contact__"), changed_at__gte=start, changed_at__lt=end)
    moves = sorted(changes.exclude(from_status="").values("from_status", "to_status").annotate(n=Count("pk")).order_by(),
                   key=lambda m: (STATUSES.index(m["from_status"]), STATUSES.index(m["to_status"])))  # pipeline order
    wins = changes.filter(to_status="won").aggregate(
        n=Count("pk"), days=Avg(ExpressionWrapper(F("changed_at") - F("contact__created_at"), output_field=DurationField())),
    )
    people = [_with_rates({"id": p.pk, "name": p.full_name, "department": p.department.name if p.department else None,
                           **{k: v for k, v in by_person.get(p.pk, EMPTY_FUNNEL).items()}}) for p in scope.people]
    if None in by_person:
        people.append(_with_rates({"id": None, "name": None, "department": None, **by_person[None]}))
    return {
        "from": first, "to": last, "funnel": totals, "people": people,
        "moves": [{"from": m["from_status"], "to": m["to_status"], "count": m["n"]} for m in moves],
        "won_in_period": wins["n"], "average_days_to_win": round(wins["days"].total_seconds() / 86400, 1) if wins["days"] else None,
    }
