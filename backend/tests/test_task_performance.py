"""Query counts for the main task endpoints: they must not grow with the number of tasks.

Each endpoint is measured on a small dataset, then again after many more tasks (with checklists,
comments, activity and several assignees) are added. The count must be the same both times and
within the limit below, so an N+1 query anywhere in these pages fails here.
"""
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import User
from apps.tasks.models import ChecklistItem, Task, TaskComment

from .task_dataset import analyze, build

pytestmark = pytest.mark.django_db

# Most queries any role needs (permissions, settings, counts and the page itself).
LIMITS = {
    "list": 3,
    "board": 13,
    "calendar": 5,
    "workload": 1,
    "dashboard": 23,  # Phase 4: "My bookings today" (1), "Today's meetings and bookings" (2), "Pending approvals" (leave + bookings, 2)
    "contact_tasks": 3,
    "company_tasks": 3,
    "contact_timeline": 6,
    "company_timeline": 8,
    "pipeline": 7,
    "search": 7,
    "detail": 2,
    "activity": 6,
}


@pytest.fixture
def setup(make_user):
    people = [make_user(f"s{i}@t.com") for i in range(5)] + [make_user(f"o{i}@t.com", department="ops") for i in range(3)]
    manager = make_user("m@t.com", User.Role.MANAGER)
    admin = make_user("a@t.com", User.Role.ADMIN, department=None)
    team = people + [manager]
    data = build(team, 12)
    contact, company = data["contacts"][0], data["companies"][0]
    task = Task.objects.filter(contact=contact).first()
    TaskComment.objects.create(task=task, author=people[0], body="First")  # so every prefetch runs from the start
    return {"team": team, "roles": {"admin": admin, "manager": manager, "staff": people[0]},
            "contact": contact, "company": company, "task": task}


def grow(setup):
    """Add many more tasks, with more of them on the measured contact, company and task."""
    team, contact, company, task = setup["team"], setup["contact"], setup["company"], setup["task"]
    build(team, 300, seed=2)
    newest = list(Task.objects.order_by("-pk").values_list("pk", flat=True)[:60])
    Task.objects.filter(pk__in=newest[:30]).update(contact=contact, company=None)
    Task.objects.filter(pk__in=newest[30:]).update(contact=None, company=company)
    ChecklistItem.objects.bulk_create([ChecklistItem(task=task, text=f"Item {i}", position=i) for i in range(20)])
    TaskComment.objects.bulk_create([TaskComment(task=task, author=team[i % 3], body=f"Note {i}") for i in range(20)])
    analyze()  # statistics after the extra rows too


def calls(setup, role):
    contact, company, task = setup["contact"], setup["company"], setup["task"]
    out = {
        "list": ("/api/v1/tasks/", {"page_size": 100}),
        "board": ("/api/v1/tasks/board/", {}),
        "calendar": ("/api/v1/tasks/calendar/", {"start": "2026-09-01", "end": "2026-11-01"}),
        "dashboard": ("/api/v1/dashboard/", {}),
        "contact_tasks": ("/api/v1/tasks/", {"contact": contact.pk, "recent": "true", "page_size": 50}),
        "company_tasks": ("/api/v1/tasks/", {"related_company": company.pk, "recent": "true", "page_size": 50}),
        "contact_timeline": ("/api/v1/timeline/", {"contact": contact.pk}),
        "company_timeline": ("/api/v1/timeline/", {"company": company.pk}),
        "pipeline": ("/api/v1/contacts/pipeline/", {}),
        "search": ("/api/v1/search/", {"q": "Task 1"}),
    }
    if role == "admin":  # the admin sees every task, so the task pages are measured for them
        out["detail"] = (f"/api/v1/tasks/{task.pk}/", {})
        out["activity"] = (f"/api/v1/tasks/{task.pk}/activity/", {})
    if role != "staff":
        out["workload"] = ("/api/v1/tasks/workload/", {})
    return out


def measure(client, url, params):
    client.get(url, params)  # warm the settings cache
    with CaptureQueriesContext(connection) as ctx:
        res = client.get(url, params)
    assert res.status_code == 200, (url, res.status_code)
    return len(ctx)


@pytest.mark.parametrize("role", ["admin", "manager", "staff"])
def test_task_endpoints_do_not_grow_with_data(role, setup, client_for):
    client = client_for(setup["roles"][role])
    small = {name: measure(client, url, params) for name, (url, params) in calls(setup, role).items()}
    grow(setup)
    large = {name: measure(client, url, params) for name, (url, params) in calls(setup, role).items()}
    assert large == small, f"query count grew with the data: {small} -> {large}"
    over = {name: n for name, n in large.items() if n > LIMITS[name]}
    assert not over, f"more queries than expected: {over}"


def test_dataset_is_realistic(setup):
    """The grown dataset really has the shape the counts above are measured on."""
    grow(setup)
    assert Task.objects.count() == 312
    assert Task.assignees.through.objects.values("task").distinct().count() == 312
    assert Task.assignees.through.objects.count() > 312 * 1.5  # several assignees on many tasks
    assert ChecklistItem.objects.count() > 500 and TaskComment.objects.count() > 250
    assert set(Task.objects.values_list("status", flat=True)) == {"todo", "in_progress", "review", "done"}


@pytest.mark.parametrize("name", ["list", "board", "calendar"])
def test_settings_cache_is_not_read_per_task(name, setup, client_for):
    """The office time zone (for "overdue") comes from the cache, which is Redis in production:
    it is read a fixed number of times per response, not once per task."""
    from unittest import mock

    from apps.core.safe_cache import safe_cache

    client = client_for(setup["roles"]["admin"])
    url, params = calls(setup, "admin")[name]

    def reads():
        client.get(url, params)
        with mock.patch.object(safe_cache, "get", wraps=safe_cache.get) as spy:
            client.get(url, params)
        return spy.call_count

    small = reads()
    grow(setup)
    assert reads() == small
