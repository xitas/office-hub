"""Tasks across the CRM: contact/company task lists, timeline entries, pipeline cards, dashboard, search, workload."""
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from unittest import mock

import pytest

from apps.contacts.models import Company, Contact
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db

TASKS = "/api/v1/tasks/"
DAY = date(2026, 10, 14)  # a Wednesday


def at_office(day, hour=10, minute=0):
    moment = datetime.combine(day, time(hour, minute), tzinfo=dt_timezone.utc) - timedelta(hours=5)
    return mock.patch("django.utils.timezone.now", return_value=moment)


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {
        "admin": admin, "manager": manager, "staff": staff,
        "colleague": make_user("colleague@test.com", full_name="Sara Colleague"),
        "outsider": make_user("ops.person@test.com", department="ops", full_name="Omar Ops"),
    }


@pytest.fixture
def crm(people):
    acme = Company.objects.create(name="Acme", assigned_to=people["staff"])
    ali = Contact.objects.create(first_name="Ali", last_name="Khan", company=acme, assigned_to=people["staff"])
    return {"acme": acme, "ali": ali}


def make(title, creator, assignees=(), **extra):
    task = Task.objects.create(title=title, created_by=creator, **extra)
    task.assignees.set(assignees or [creator])
    return task


def titles(res):
    return sorted(t["title"] for t in res.data["results"])


# ================================================================ contact / company task lists


def test_linked_tasks_on_contact_and_company(client_for, people, crm):
    s = people["staff"]
    make("Call Ali", s, contact=crm["ali"])
    make("Acme renewal", s, company=crm["acme"])
    make("Not linked", s)
    old = make("Sent brochure", s, contact=crm["ali"], status="done")
    Task.objects.filter(pk=old.pk).update(completed_at=old.completed_at - timedelta(days=30))
    make("Done yesterday", s, contact=crm["ali"], status="done")
    c = client_for(s)
    assert titles(c.get(TASKS, {"contact": crm["ali"].pk, "recent": "true"})) == ["Call Ali", "Done yesterday"]
    # A company also lists its contacts' tasks (with the contact's name on each).
    res = c.get(TASKS, {"related_company": crm["acme"].pk, "recent": "true"})
    assert titles(res) == ["Acme renewal", "Call Ali", "Done yesterday"]
    assert {t["title"]: t["contact_name"] for t in res.data["results"]}["Call Ali"] == "Ali Khan"


def test_linked_tasks_respect_task_visibility(client_for, people, crm):
    make("Ops task on Ali", people["outsider"], contact=crm["ali"])
    assert titles(client_for(people["staff"]).get(TASKS, {"contact": crm["ali"].pk})) == []
    assert titles(client_for(people["admin"]).get(TASKS, {"contact": crm["ali"].pk})) == ["Ops task on Ali"]


def test_add_task_with_link_prefilled(client_for, people, crm):
    res = client_for(people["staff"]).post(TASKS, {"title": "Send quote", "company": crm["acme"].pk}, format="json")
    assert res.status_code == 201 and res.data["company_name"] == "Acme"


# ================================================================ timeline


def task_events(client, **target):
    items = client.get("/api/v1/timeline/", {**target, "type": "task"}).data["results"]
    return [(i["details"]["event"], i["summary"], (i["contact"] or {}).get("name")) for i in items]


def test_task_events_on_contact_and_company_timeline(client_for, people, crm):
    c = client_for(people["staff"])
    tid = c.post(TASKS, {"title": "Call Ali", "contact": crm["ali"].pk}, format="json").data["id"]
    c.patch(f"{TASKS}{tid}/", {"status": "in_progress"}, format="json")  # not shown: only created/completed/reopened
    c.patch(f"{TASKS}{tid}/", {"status": "done"}, format="json")
    c.patch(f"{TASKS}{tid}/", {"status": "todo"}, format="json")
    assert task_events(c, contact=crm["ali"].pk) == [
        ("reopened", "Call Ali", "Ali Khan"), ("completed", "Call Ali", "Ali Khan"), ("created", "Call Ali", "Ali Khan"),
    ]
    # The company's timeline rolls up its contacts' tasks, marked with the contact.
    assert [e[0] for e in task_events(c, company=crm["acme"].pk)] == ["reopened", "completed", "created"]
    entry = c.get("/api/v1/timeline/", {"contact": crm["ali"].pk, "type": "task"}).data["results"][0]
    assert entry["details"]["task_id"] == tid and entry["created_by_name"] == people["staff"].full_name and not entry["editable"]


def test_task_events_hidden_when_the_task_is_hidden(client_for, people, crm):
    """The admin can see Ali; a task an Ops person keeps to themselves stays hidden from Ali's staff owner."""
    o = client_for(people["outsider"])
    crm["ali"].assigned_to = people["outsider"]
    crm["ali"].save()
    o.post(TASKS, {"title": "Private ops task", "contact": crm["ali"].pk}, format="json")
    crm["ali"].assigned_to = people["staff"]
    crm["ali"].save()
    assert task_events(client_for(people["staff"]), contact=crm["ali"].pk) == []
    assert len(task_events(client_for(people["admin"]), contact=crm["ali"].pk)) == 1


# ================================================================ pipeline cards


def test_pipeline_cards_show_open_tasks_and_next_due(client_for, people, crm):
    s = people["staff"]
    make("Later", s, contact=crm["ali"], due_date=DAY + timedelta(days=9))
    make("Sooner", s, contact=crm["ali"], due_date=DAY + timedelta(days=2))
    make("Done", s, contact=crm["ali"], status="done", due_date=DAY)
    make("Hidden", people["outsider"], contact=crm["ali"], due_date=DAY)
    card = client_for(s).get("/api/v1/contacts/pipeline/").data["columns"][0]["cards"][0]
    assert card["open_tasks"] == 2 and card["next_due"] == str(DAY + timedelta(days=2))
    admin_card = client_for(people["admin"]).get("/api/v1/contacts/pipeline/").data["columns"][0]["cards"][0]
    assert admin_card["open_tasks"] == 3 and admin_card["next_due"] == str(DAY)


# ================================================================ dashboard


@pytest.fixture
def week(people):
    s, c, o = people["staff"], people["colleague"], people["outsider"]
    make("Due today", s, due_date=DAY, due_time=time(15, 0), priority="high")
    make("Overdue", s, due_date=DAY - timedelta(days=2))
    make("In 3 days", s, due_date=DAY + timedelta(days=3))
    make("In 9 days", s, due_date=DAY + timedelta(days=9))
    make("Colleague overdue", c, due_date=DAY - timedelta(days=1))
    make("Ops open", o)
    return s


def test_my_task_widgets(client_for, people, week):
    with at_office(DAY):
        data = client_for(people["staff"]).get("/api/v1/dashboard/").data
    assert [t["title"] for t in data["tasks_today"]] == ["Due today"]
    assert data["tasks_today"][0]["due_time"] == "15:00" and data["tasks_today"][0]["priority"] == "high"
    assert [t["title"] for t in data["overdue"]] == ["Overdue"] and data["overdue"][0]["is_overdue"] is True
    assert [t["title"] for t in data["upcoming_deadlines"]] == ["In 3 days"]


@pytest.mark.parametrize("who,expected", [
    ("staff", None),
    # Staff: due today, overdue, in 3 days and in 9 days are all open; one is overdue.
    ("manager", {"Staff": (4, 1), "Sara Colleague": (1, 1), "Manager": (0, 0)}),
    ("admin", {"Staff": (4, 1), "Sara Colleague": (1, 1), "Omar Ops": (1, 0)}),
])
def test_team_workload_per_role(client_for, people, week, who, expected):
    with at_office(DAY):
        rows = client_for(people[who]).get("/api/v1/dashboard/").data["team_workload"]
    if expected is None:
        assert rows is None
        return
    got = {r["name"]: (r["open"], r["overdue"]) for r in rows}
    for name, counts in expected.items():
        assert got[name] == counts
    if who == "manager":
        assert "Omar Ops" not in got  # other departments aren't in a manager's workload
    assert rows[0]["overdue"] >= rows[-1]["overdue"]  # most overdue first


def test_task_completion_this_week(client_for, people):
    s, c = people["staff"], people["colleague"]
    with at_office(DAY - timedelta(days=9)):  # last week: not counted
        make("Old", s, status="done")
    with at_office(DAY - timedelta(days=1)):  # Tuesday
        make("Mine done", s, status="done")
        make("Colleague done", c, status="done")
    with at_office(DAY):
        make("Mine new", s)
        staff = client_for(s).get("/api/v1/dashboard/").data["task_completion"]
        manager = client_for(people["manager"]).get("/api/v1/dashboard/").data["task_completion"]
    assert staff["week_start"] == date(2026, 10, 12)  # Monday (organization default)
    assert (staff["done"], staff["created"]) == (1, 2)
    assert (manager["done"], manager["created"]) == (2, 3)  # the department
    tuesday = next(d for d in manager["days"] if d["date"] == DAY - timedelta(days=1))
    assert (tuesday["done"], tuesday["created"]) == (2, 2)
    assert len(manager["days"]) == 7


def test_week_start_follows_organization(client_for, people):
    from apps.core.models import OrganizationSettings

    org = OrganizationSettings.get_solo()
    org.week_start = 6  # Saturday
    org.save()
    with at_office(DAY):
        assert client_for(people["staff"]).get("/api/v1/dashboard/").data["task_completion"]["week_start"] == date(2026, 10, 10)


# ================================================================ global search


def test_search_finds_visible_tasks_only(client_for, people, crm):
    make("Quarterly budget review", people["staff"], [people["staff"], people["colleague"]], due_date=DAY, status="in_progress")
    make("Quarterly ops audit", people["outsider"])
    hits = client_for(people["staff"]).get("/api/v1/search/", {"q": "quarterly"}).data["results"]["tasks"]
    assert [h["title"] for h in hits] == ["Quarterly budget review"]
    hit = hits[0]
    assert hit["task_status"] == "in_progress" and hit["due_date"] == DAY and hit["url"].startswith("/tasks/")
    assert hit["subtitle"] == "Sara Colleague, Staff" or set(hit["subtitle"].split(", ")) == {"Sara Colleague", "Staff"}
    admin_hits = client_for(people["admin"]).get("/api/v1/search/", {"q": "quarterly"}).data["results"]["tasks"]
    assert len(admin_hits) == 2


# ================================================================ team page counts


def test_workload_endpoint(client_for, people, week):
    assert client_for(people["staff"]).get(f"{TASKS}workload/").status_code == 403
    with at_office(DAY):
        manager = {r["name"]: (r["open"], r["overdue"]) for r in client_for(people["manager"]).get(f"{TASKS}workload/").data}
        admin = {r["name"]: (r["open"], r["overdue"]) for r in client_for(people["admin"]).get(f"{TASKS}workload/").data}
    assert manager["Staff"] == (4, 1) and manager["Omar Ops"] == (0, 0)  # Ops tasks aren't visible to a Sales manager
    assert admin["Omar Ops"] == (1, 0)
