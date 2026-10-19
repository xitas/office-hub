"""Task reports: completion by person and department for a period, and overdue tasks as of today.

All counting happens in the database (grouped counts on the task-assignee table), so a report costs the same few
queries whether it covers five people or fifty and a week or a year. Only tasks the viewer may see are counted.

Completion, for tasks due in the period (by their due date):
- due: tasks due in the period; done: of those, completed; on time: completed on or before the due date (office
  day of completion); late: completed after it; overdue: not done and the due date has passed; still open: not done,
  due today or later. Completed in the period counts every task finished in it, whatever its due date.
- A task with several assignees counts once for each person, and once in its department's and the overall totals.
"""
from datetime import timedelta

from django.db.models import Count, F, Min, Q
from django.db.models.functions import TruncDate
from django.db.models.lookups import GreaterThan, LessThanOrEqual

from apps.core.office_time import office_today, office_tz
from apps.tasks.models import Task
from apps.tasks.rules import visible_tasks

from .scope import day_bounds

Link = Task.assignees.through
DONE = Task.Status.DONE
OVERDUE_BUCKETS = ((1, 7), (8, 30), (31, None))  # days late
MAX_TASKS_LISTED = 200


def _rate(part, whole):
    return round(part / whole, 4) if whole else None


def _completion_counts(prefix, first, last, today, start, end):
    """Count(...) expressions for one row of the completion report; `prefix` is the path to the task."""
    p = prefix
    due = Q(**{f"{p}due_date__gte": first, f"{p}due_date__lte": last})
    done = due & Q(**{f"{p}status": DONE})
    finished_day = TruncDate(f"{p}completed_at", tzinfo=office_tz())
    field = f"{p}pk" if p else "pk"
    return {
        "due": Count(field, filter=due, distinct=True),
        "done": Count(field, filter=done, distinct=True),
        "on_time": Count(field, filter=done & Q(LessThanOrEqual(finished_day, F(f"{p}due_date"))), distinct=True),
        "late": Count(field, filter=done & Q(GreaterThan(finished_day, F(f"{p}due_date"))), distinct=True),
        "overdue": Count(field, filter=due & ~Q(**{f"{p}status": DONE}) & Q(**{f"{p}due_date__lt": today}), distinct=True),
        "open": Count(field, filter=due & ~Q(**{f"{p}status": DONE}) & Q(**{f"{p}due_date__gte": today}), distinct=True),
        "completed": Count(field, filter=Q(**{f"{p}status": DONE, f"{p}completed_at__gte": start, f"{p}completed_at__lt": end}), distinct=True),
    }


def _with_rates(row: dict) -> dict:
    return {**row, "rate": _rate(row["done"], row["due"]), "on_time_rate": _rate(row["on_time"], row["due"])}


EMPTY = {"due": 0, "done": 0, "on_time": 0, "late": 0, "overdue": 0, "open": 0, "completed": 0}


def completion(user, scope, first, last) -> dict:
    """Per person, per department and overall (4 queries, whatever the size)."""
    today = office_today()
    start, end = day_bounds(first, last)
    people_ids = [p.pk for p in scope.people]
    tasks = visible_tasks(user).values("pk")
    links = Link.objects.filter(user_id__in=people_ids, task_id__in=tasks)
    counts = _completion_counts("task__", first, last, today, start, end)
    by_person = {r.pop("user_id"): r for r in links.values("user_id").annotate(**counts).order_by()}
    by_department = {r.pop("user__department_id"): r for r in links.values("user__department_id").annotate(**counts).order_by()}
    totals = Task.objects.filter(pk__in=links.values("task_id")).aggregate(**_completion_counts("", first, last, today, start, end))
    departments = {}
    for p in scope.people:
        if p.department_id not in departments:
            departments[p.department_id] = p.department.name if p.department else None
    return {
        "from": first, "to": last, "as_of": today,
        "people": [
            _with_rates({"id": p.pk, "name": p.full_name, "department": p.department.name if p.department else None,
                         **by_person.get(p.pk, EMPTY)})
            for p in scope.people
        ],
        "departments": [
            _with_rates({"id": d_id, "name": name, **by_department.get(d_id, EMPTY)})
            for d_id, name in sorted(departments.items(), key=lambda kv: kv[1] or "")
        ],
        "totals": _with_rates(totals),
    }


def overdue(user, scope) -> dict:
    """Open tasks past their due date, as of today: per person (with how late) and the most overdue tasks."""
    today = office_today()
    people_ids = [p.pk for p in scope.people]
    late = visible_tasks(user).exclude(status=DONE).filter(due_date__lt=today)
    links = Link.objects.filter(user_id__in=people_ids, task_id__in=late.values("pk"))
    buckets = {}
    for lo, hi in OVERDUE_BUCKETS:
        newest = today - timedelta(days=lo)
        q = Q(task__due_date__lte=newest)
        if hi is not None:
            q &= Q(task__due_date__gte=today - timedelta(days=hi))
        buckets[f"days_{lo}_{hi or 'plus'}"] = Count("task_id", filter=q)
    by_person = {r.pop("user_id"): r for r in links.values("user_id").annotate(
        overdue=Count("task_id"), urgent=Count("task_id", filter=Q(task__priority__in=["high", "urgent"])),
        oldest=Min("task__due_date"), **buckets,
    ).order_by()}
    in_scope = Task.objects.filter(pk__in=links.values("task_id"))
    total = in_scope.count()
    listed = (in_scope.select_related("contact", "company").prefetch_related("assignees").order_by("due_date", "pk")[:MAX_TASKS_LISTED])
    names = {p.pk: p.full_name for p in scope.people}
    empty = {"overdue": 0, "urgent": 0, "oldest": None, **{k: 0 for k in buckets}}
    return {
        "as_of": today,
        "people": [
            {"id": p.pk, "name": p.full_name, "department": p.department.name if p.department else None, **by_person.get(p.pk, empty)}
            for p in scope.people
        ],
        "total": total,
        "tasks": [
            {
                "id": t.pk, "title": t.title, "due_date": t.due_date, "days_late": (today - t.due_date).days, "priority": t.priority,
                "status": t.status, "record": t.contact.full_name if t.contact_id else t.company.name if t.company_id else None,
                "assignees": sorted(names[u.pk] for u in t.assignees.all() if u.pk in names),
            }
            for t in listed
        ],
        "buckets": [f"days_{lo}_{hi or 'plus'}" for lo, hi in OVERDUE_BUCKETS],
    }
