from datetime import datetime, time, timedelta
from unittest import mock

import pytest
from django.utils import timezone

from apps.contacts.models import Company, Contact
from apps.core.models import AuditLog
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db

TASKS = "/api/v1/tasks/"


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {
        "admin": admin,
        "manager": manager,  # Sales
        "staff": staff,  # Sales
        "colleague": make_user("colleague@test.com", full_name="Sara Colleague"),  # Sales
        "outsider": make_user("ops.person@test.com", department="ops", full_name="Omar Ops"),
        "ops_manager": make_user("ops.manager@test.com", role="manager", department="ops"),
        "loner": make_user("loner@test.com", department=None),
    }


def make(title, creator, assignees=(), **extra):
    task = Task.objects.create(title=title, created_by=creator, **extra)
    task.assignees.set(assignees or [creator])
    return task


def titles(res):
    return sorted(t["title"] for t in res.data["results"])


# ================================================================ model


def test_completed_at_follows_status(people):
    task = make("Send quote", people["staff"])
    assert task.completed_at is None
    task.status = Task.Status.DONE
    task.save()
    assert task.completed_at is not None
    first = task.completed_at
    task.title = "Send quote v2"
    task.save()
    assert task.completed_at == first  # stays while Done
    task.status = Task.Status.REVIEW
    task.save(update_fields=["status"])
    task.refresh_from_db()
    assert task.completed_at is None


def test_overdue_rules(people):
    today = timezone.localdate()
    assert make("Yesterday", people["staff"], due_date=today - timedelta(days=1)).is_overdue
    assert not make("Tomorrow", people["staff"], due_date=today + timedelta(days=1)).is_overdue
    assert not make("No date", people["staff"]).is_overdue
    assert not make("Done late", people["staff"], due_date=today - timedelta(days=3), status="done").is_overdue
    now = timezone.make_aware(datetime.combine(today, time(15, 0)))
    with mock.patch("django.utils.timezone.now", return_value=now):
        assert make("Today 10:00", people["staff"], due_date=today, due_time=time(10, 0)).is_overdue
        assert not make("Today 17:00", people["staff"], due_date=today, due_time=time(17, 0)).is_overdue
        assert not make("Today, no time", people["staff"], due_date=today).is_overdue  # until the end of the day


# ================================================================ create / view / edit / delete


def test_create_defaults_to_me_and_is_audited(client_for, people):
    c = client_for(people["staff"])
    res = c.post(TASKS, {"title": "  Call   back Ali  ", "priority": "high", "due_date": "2026-11-01"}, format="json")
    assert res.status_code == 201, res.data
    assert res.data["title"] == "Call back Ali"
    assert res.data["assignees"] == [people["staff"].pk]
    assert res.data["status"] == "todo" and res.data["created_by_name"] == people["staff"].full_name
    assert res.data["can_delete"] is True
    log = AuditLog.objects.get(action=AuditLog.Action.CREATE, object_id=str(res.data["id"]))
    assert log.changes["assignees"] == people["staff"].full_name and log.changes["priority"] == "high"


def test_view_edit_and_status_change(client_for, people):
    task = make("Draft proposal", people["staff"])
    c = client_for(people["staff"])
    assert c.get(f"{TASKS}{task.pk}/").data["title"] == "Draft proposal"
    res = c.patch(f"{TASKS}{task.pk}/", {"status": "done"}, format="json")
    assert res.status_code == 200 and res.data["completed_at"] is not None
    log = AuditLog.objects.filter(action=AuditLog.Action.UPDATE, object_id=str(task.pk)).latest("timestamp")
    assert log.changes["status"] == ["todo", "done"]
    res = c.patch(f"{TASKS}{task.pk}/", {"assignees": [people["staff"].pk, people["colleague"].pk]}, format="json")
    assert res.status_code == 200
    log = AuditLog.objects.filter(action=AuditLog.Action.UPDATE, object_id=str(task.pk)).latest("timestamp")
    assert log.changes["assignees"] == ["Staff", "Sara Colleague, Staff"]


def test_validation(client_for, people):
    c = client_for(people["staff"])
    assert c.post(TASKS, {"title": "   "}, format="json").status_code == 400
    assert c.post(TASKS, {"title": "x", "priority": "whenever"}, format="json").status_code == 400
    assert c.post(TASKS, {"title": "x", "assignees": []}, format="json").status_code == 400
    res = c.post(TASKS, {"title": "x", "due_time": "10:00"}, format="json")
    assert res.status_code == 400 and "due_time" in res.data["errors"]


def test_link_to_visible_contact_or_company_only(client_for, people):
    mine = Contact.objects.create(first_name="Ali", assigned_to=people["staff"])
    hidden = Contact.objects.create(first_name="Hidden", assigned_to=people["outsider"])
    acme = Company.objects.create(name="Acme", assigned_to=people["staff"])
    c = client_for(people["staff"])
    res = c.post(TASKS, {"title": "Call Ali", "contact": mine.pk}, format="json")
    assert res.status_code == 201 and res.data["contact_name"] == "Ali"
    assert c.post(TASKS, {"title": "Peek", "contact": hidden.pk}, format="json").status_code == 400
    both = c.post(TASKS, {"title": "Both", "contact": mine.pk, "company": acme.pk}, format="json")
    assert both.status_code == 400 and "company" in both.data["errors"]
    filtered = c.get(TASKS, {"contact": mine.pk})
    assert titles(filtered) == ["Call Ali"]


# ================================================================ visibility per role


@pytest.fixture
def board(people):
    return {
        "own": make("Own", people["staff"]),
        "assigned_to_staff": make("Assigned to staff", people["manager"], [people["staff"]]),
        "colleague": make("Colleague's", people["colleague"]),
        "ops": make("Ops task", people["outsider"]),
        "cross": make("Ops task for sales", people["outsider"], [people["colleague"]]),
    }


@pytest.mark.parametrize("who,expected", [
    ("staff", ["Assigned to staff", "Own"]),
    ("colleague", ["Colleague's", "Ops task for sales"]),
    ("manager", ["Assigned to staff", "Colleague's", "Ops task for sales", "Own"]),  # department, either side
    ("ops_manager", ["Ops task", "Ops task for sales"]),
    ("admin", ["Assigned to staff", "Colleague's", "Ops task", "Ops task for sales", "Own"]),
])
def test_visibility_per_role(client_for, people, board, who, expected):
    assert titles(client_for(people[who]).get(TASKS)) == expected


def test_hidden_tasks_are_not_found(client_for, people, board):
    c = client_for(people["staff"])
    assert c.get(f"{TASKS}{board['ops'].pk}/").status_code == 404
    assert c.patch(f"{TASKS}{board['ops'].pk}/", {"title": "x"}, format="json").status_code == 404
    assert c.delete(f"{TASKS}{board['ops'].pk}/").status_code == 404


# ================================================================ assignment rules


@pytest.mark.parametrize("who,target,allowed", [
    ("staff", "staff", True),
    ("staff", "colleague", True),  # same department
    ("staff", "manager", True),
    ("staff", "outsider", False),
    ("manager", "colleague", True),
    ("manager", "outsider", False),
    ("ops_manager", "outsider", True),
    ("ops_manager", "staff", False),
    ("admin", "outsider", True),
    ("admin", "loner", True),
    ("loner", "loner", True),  # no department: only themselves
    ("loner", "staff", False),
])
def test_assignment_rules(client_for, people, who, target, allowed):
    res = client_for(people[who]).post(TASKS, {"title": "t", "assignees": [people[target].pk]}, format="json")
    assert res.status_code == (201 if allowed else 400), res.data
    if not allowed:
        assert "assignees" in res.data["errors"]


def test_existing_assignees_do_not_block_edits(client_for, people):
    # An admin put someone from another department on a Sales task; a Sales manager can still edit it.
    task = make("Shared", people["admin"], [people["staff"], people["outsider"]])
    c = client_for(people["manager"])
    res = c.patch(f"{TASKS}{task.pk}/", {"title": "Shared v2", "assignees": [people["staff"].pk, people["outsider"].pk, people["colleague"].pk]}, format="json")
    assert res.status_code == 200, res.data
    res = c.patch(f"{TASKS}{task.pk}/", {"assignees": [people["staff"].pk, people["ops_manager"].pk]}, format="json")
    assert res.status_code == 400  # adding someone new from Operations is not allowed


@pytest.mark.parametrize("who,creator,allowed", [
    ("staff", "staff", True),
    ("staff", "manager", False),  # assigned to them, but not theirs to delete
    ("manager", "colleague", True),
    ("admin", "outsider", True),
])
def test_delete_rules(client_for, people, who, creator, allowed):
    task = make("Delete me", people[creator], [people[creator], people[who]] if who != "admin" else [people[creator]])
    c = client_for(people[who])
    assert c.get(f"{TASKS}{task.pk}/").data["can_delete"] is allowed
    res = c.delete(f"{TASKS}{task.pk}/")
    assert res.status_code == (204 if allowed else 403)
    assert Task.objects.filter(pk=task.pk).exists() is not allowed
    assert AuditLog.objects.filter(action=AuditLog.Action.DELETE, object_id=str(task.pk)).exists() is allowed


# ================================================================ filters, search, sorting


@pytest.fixture
def dated(people):
    today = timezone.localdate()
    s, m = people["staff"], people["manager"]
    return {
        "overdue": make("Overdue urgent", m, [s], due_date=today - timedelta(days=2), priority="urgent"),
        "today": make("Due today", s, due_date=today, priority="low"),
        "soon": make("Next week", s, due_date=today + timedelta(days=5), priority="high", status="in_progress"),
        "later": make("Next month", m, [m], due_date=today + timedelta(days=30), status="review"),
        "nodate": make("Someday", s, priority="medium"),
        "done": make("Finished late", s, due_date=today - timedelta(days=5), status="done"),
    }


@pytest.mark.parametrize("params,expected", [
    ({"mine": "true"}, ["Next month"]),  # as the manager
    ({"due": "overdue"}, ["Overdue urgent"]),
    ({"overdue": "true"}, ["Overdue urgent"]),
    ({"due": "today"}, ["Due today"]),
    ({"due": "upcoming"}, ["Next week"]),
    ({"due": "none"}, ["Someday"]),
    ({"status": "in_progress,review"}, ["Next month", "Next week"]),
    ({"priority": "urgent,high"}, ["Next week", "Overdue urgent"]),
    ({"search": "next"}, ["Next month", "Next week"]),
    ({"created_by": "MANAGER"}, ["Next month", "Overdue urgent"]),
    ({"assigned_to": "MANAGER"}, ["Next month"]),
])
def test_filters(client_for, people, dated, params, expected):
    params = {k: str(people["manager"].pk) if v == "MANAGER" else v for k, v in params.items()}
    assert titles(client_for(people["manager"]).get(TASKS, params)) == expected


def test_due_date_range(client_for, people, dated):
    today = timezone.localdate()
    res = client_for(people["manager"]).get(TASKS, {"due_from": str(today), "due_to": str(today + timedelta(days=7))})
    assert titles(res) == ["Due today", "Next week"]


def test_sorting(client_for, people, dated):
    c = client_for(people["manager"])
    default = [t["title"] for t in c.get(TASKS).data["results"]]
    assert default == ["Overdue urgent", "Due today", "Next week", "Next month", "Someday", "Finished late"]
    by_priority = [t["title"] for t in c.get(TASKS, {"ordering": "priority"}).data["results"]]
    assert by_priority[0] == "Overdue urgent" and by_priority[1] == "Next week"
    by_due_desc = [t["title"] for t in c.get(TASKS, {"ordering": "-due"}).data["results"]]
    assert by_due_desc[:2] == ["Next month", "Next week"] and by_due_desc[-1] == "Someday"
    assert c.get(TASKS).data["results"][0]["is_overdue"] is True


def test_pagination(client_for, people):
    for i in range(30):
        make(f"T{i}", people["staff"])
    res = client_for(people["staff"]).get(TASKS)
    assert res.data["count"] == 30 and len(res.data["results"]) == 25 and res.data["next"]


def test_permissions_listed_for_frontend(client_for, people):
    perms = client_for(people["staff"]).get("/api/v1/auth/me/").data["permissions"]
    assert {"tasks.view", "tasks.create", "tasks.edit", "tasks.delete", "tasks.assign_others"} <= set(perms)


def test_task_text_in_urdu(client_for, people):
    make("Ali", people["staff"], status="in_progress", priority="urgent")
    row = client_for(people["staff"]).get(TASKS, HTTP_ACCEPT_LANGUAGE="ur").data["results"][0]
    assert row["status_label"] == "جاری" and row["priority_label"] == "فوری"


def test_seed_creates_demo_tasks():
    import io

    from django.core.management import call_command

    call_command("seed_demo", stdout=io.StringIO())
    count = Task.objects.count()
    call_command("seed_demo", stdout=io.StringIO())  # idempotent
    assert Task.objects.count() == count >= 28
    today = timezone.localdate()
    assert Task.objects.filter(due_date__lt=today).exclude(status="done").exists()
    assert Task.objects.filter(due_date=today).exists()
    assert set(Task.objects.values_list("status", flat=True)) == {"todo", "in_progress", "review", "done"}
    assert set(Task.objects.values_list("priority", flat=True)) == {"low", "medium", "high", "urgent"}
    assert all(t.assignees.exists() for t in Task.objects.all())
    for task in Task.objects.prefetch_related("assignees").select_related("created_by"):
        creator = task.created_by
        if creator.role != "admin":
            assert all(u.department_id == creator.department_id for u in task.assignees.all())
