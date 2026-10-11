"""Tasks in the rest of the CRM: contact/company timelines, dashboard widgets, global search, team workload.

Everything here is scoped with rules.visible_tasks, so nobody learns about tasks they couldn't open.
"""
from datetime import timedelta

from django.db.models import Count, Q

from apps.accounts.models import User
from apps.core.office_time import office_now
from apps.core.permissions import ADMIN, MANAGER, has_perm

from .models import Task, TaskActivity, overdue_q
from .rules import visible_tasks

UPCOMING_DAYS = 7
WIDGET_LIMIT = 10


# ================================================================ timeline (contact / company activity)


def timeline_entries(user, contact_ids, company_ids):
    """Task created / completed / reopened, for tasks linked to these contacts or companies."""
    from apps.timeline.registry import auto_entry

    if not has_perm(user, "tasks", "view"):
        return []
    tasks = visible_tasks(user).filter(Q(contact_id__in=contact_ids) | Q(company_id__in=company_ids))
    events = (
        TaskActivity.objects.filter(task__in=tasks)
        .filter(Q(kind="created") | Q(kind="status", data__new="done") | Q(kind="status", data__old="done"))
        .select_related("task__contact", "task__company", "actor")
    )
    entries = []
    for a in events:
        if a.kind == "created":
            event = "created"
        elif a.data.get("new") == "done":
            event = "completed"
        else:
            event = "reopened"
        task = a.task
        entries.append(auto_entry(
            uid=f"task:{a.pk}", kind="task", occurred_at=a.created_at, summary=task.title, user=a.actor,
            details={"event": event, "task_id": task.pk, "status": task.status}, contact=task.contact, company=task.company,
        ))
    return entries


# ================================================================ dashboard


def _task_item(task) -> dict:
    return {
        "id": task.pk,
        "title": task.title,
        "url": f"/tasks/{task.pk}",
        "due_date": task.due_date,
        "due_time": task.due_time.strftime("%H:%M") if task.due_time else None,
        "time": None,
        "priority": task.priority,
        "status": task.status,
        "is_overdue": task.is_overdue,
    }


def _my_open(user):
    return Task.objects.filter(assignees=user).exclude(status=Task.Status.DONE)


def tasks_today(user):
    if not has_perm(user, "tasks", "view"):
        return None
    today = office_now().date()
    return [_task_item(t) for t in _my_open(user).filter(due_date=today).order_by("due_time", "-priority")[:WIDGET_LIMIT]]


def overdue(user):
    if not has_perm(user, "tasks", "view"):
        return None
    today = office_now().date()
    qs = _my_open(user).filter(overdue_q()).exclude(due_date=today)  # today's late items stay under "today"
    return [_task_item(t) for t in qs.order_by("due_date", "due_time")[:WIDGET_LIMIT]]


def upcoming(user):
    if not has_perm(user, "tasks", "view"):
        return None
    today = office_now().date()
    qs = _my_open(user).filter(due_date__gt=today, due_date__lte=today + timedelta(days=UPCOMING_DAYS))
    return [_task_item(t) for t in qs.order_by("due_date", "due_time")[:WIDGET_LIMIT]]


def workload(user, people=None) -> list[dict]:
    """Open and overdue tasks per person, counted over the tasks this user can see."""
    if people is None:
        people = User.objects.filter(is_active=True)
    visible = visible_tasks(user).exclude(status=Task.Status.DONE)
    rows = (
        User.objects.filter(pk__in=people.values("pk"))
        .annotate(
            open_tasks=Count("tasks", filter=Q(tasks__in=visible), distinct=True),
            overdue_tasks=Count("tasks", filter=Q(tasks__in=visible.filter(overdue_q())), distinct=True),
        )
        .order_by("-overdue_tasks", "-open_tasks", "full_name")
    )
    return [
        {"user_id": u.pk, "name": u.full_name, "avatar": u.avatar.url if u.avatar else None, "open": u.open_tasks, "overdue": u.overdue_tasks}
        for u in rows
    ]


def team_workload(user):
    """Managers: their department. Admins: everyone. Staff: not shown."""
    if user.role == ADMIN or user.is_superuser:
        people = User.objects.filter(is_active=True)
    elif user.role == MANAGER and user.department_id:
        people = User.objects.filter(is_active=True, department_id=user.department_id)
    else:
        return None
    return workload(user, people)


def _week_start(today, org_week_start: int):
    """org_week_start: 0 = Sunday, 1 = Monday, 6 = Saturday (Organization settings)."""
    python_weekday = (org_week_start - 1) % 7  # Monday = 0 in Python
    return today - timedelta(days=(today.weekday() - python_weekday) % 7)


def task_completion(user):
    """This week (from the organization's week start): tasks completed vs created, per day.

    Staff count their own tasks, managers their department's, admins everyone's.
    """
    if not has_perm(user, "tasks", "view"):
        return None
    from apps.core.models import OrganizationSettings

    now = office_now()
    start = _week_start(now.date(), OrganizationSettings.cached().week_start)
    tz = now.tzinfo
    since = now.replace(year=start.year, month=start.month, day=start.day, hour=0, minute=0, second=0, microsecond=0)
    scope = visible_tasks(user) if (user.role in (ADMIN, MANAGER) or user.is_superuser) else Task.objects.filter(assignees=user)
    # (pk, time) pairs, so tasks with equal timestamps are never merged (e.g. if the scope is made DISTINCT).
    done = [at for _pk, at in scope.filter(completed_at__gte=since).values_list("pk", "completed_at")]
    created = [at for _pk, at in scope.filter(created_at__gte=since).values_list("pk", "created_at")]
    days = []
    for i in range(7):
        day = start + timedelta(days=i)
        days.append({
            "date": day,
            "done": sum(1 for d in done if d.astimezone(tz).date() == day),
            "created": sum(1 for d in created if d.astimezone(tz).date() == day),
        })
    return {"week_start": start, "done": len(done), "created": len(created), "days": days}


# ================================================================ global search


def search_queryset(user):
    return visible_tasks(user).prefetch_related("assignees")


def search_hit(task, viewer) -> dict:
    names = [u.full_name for u in task.assignees.all()]
    return {
        "id": task.pk,
        "title": task.title,
        "subtitle": ", ".join(names[:3]) + (f" +{len(names) - 3}" if len(names) > 3 else ""),
        "url": f"/tasks/{task.pk}",
        "task_status": task.status,
        "due_date": task.due_date,
        "is_overdue": task.is_overdue,
    }


def register():
    from apps.core import search
    from apps.dashboard import registry as dashboard
    from apps.timeline import registry as timeline

    timeline.register_provider("task", timeline_entries)
    dashboard.register("tasks_today", tasks_today)
    dashboard.register("overdue", overdue)
    dashboard.register("upcoming_deadlines", upcoming)
    dashboard.register("team_workload", team_workload)
    dashboard.register("task_completion", task_completion)
    search.register(
        "tasks", queryset=search_queryset, fields=["title", "description"], serialize=search_hit, permission=("tasks", "view"),
    )
