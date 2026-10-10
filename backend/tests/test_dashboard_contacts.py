import pytest

from apps.contacts.models import Company, Contact, ContactStatusChange
from apps.timeline.models import TimelineEntry

pytestmark = pytest.mark.django_db

DASHBOARD = "/api/v1/dashboard/"


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {
        "admin": admin, "manager": manager, "staff": staff,
        "colleague": make_user("colleague@test.com"),
        "outsider": make_user("ops.person@test.com", department="ops"),
    }


@pytest.fixture
def data(people):
    mine = Contact.objects.create(first_name="Mine", status="won", assigned_to=people["staff"])
    Contact.objects.create(first_name="Mine2", status="new", assigned_to=people["staff"])
    colleague = Contact.objects.create(first_name="Colleague", status="contacted", assigned_to=people["colleague"])
    outsider = Contact.objects.create(first_name="Outsider", status="lost", assigned_to=people["outsider"])
    acme = Company.objects.create(name="Acme", assigned_to=people["staff"])
    TimelineEntry.objects.create(kind="note", summary="mine note", contact=mine, created_by=people["staff"])
    TimelineEntry.objects.create(kind="call", summary="company call", company=acme, created_by=people["staff"],
                                 details={"direction": "out", "outcome": "connected"})
    TimelineEntry.objects.create(kind="note", summary="colleague note", contact=colleague, created_by=people["colleague"])
    TimelineEntry.objects.create(kind="note", summary="outsider note", contact=outsider, created_by=people["outsider"])
    TimelineEntry.objects.create(kind="imported", summary="file.csv", contact=mine, created_by=people["staff"])
    ContactStatusChange.objects.create(contact=mine, from_status="new", to_status="won", reason="Signed", changed_by=people["staff"])
    return {"mine": mine}


def counts(res):
    return {c["status"]: c["count"] for c in res.data["contacts_by_status"]["counts"]}


@pytest.mark.parametrize("who,scope,expected", [
    ("staff", "mine", {"new": 1, "contacted": 0, "in_discussion": 0, "won": 1, "lost": 0}),
    ("manager", "department", {"new": 1, "contacted": 1, "in_discussion": 0, "won": 1, "lost": 0}),
    ("admin", "all", {"new": 1, "contacted": 1, "in_discussion": 0, "won": 1, "lost": 1}),
])
def test_contacts_by_status_is_scoped(client_for, people, data, who, scope, expected):
    res = client_for(people[who]).get(DASHBOARD)
    assert res.data["contacts_by_status"]["scope"] == scope
    assert counts(res) == expected
    assert res.data["contacts_by_status"]["total"] == sum(expected.values())


@pytest.mark.parametrize("who,expected", [
    ("staff", {"mine note", "company call", "Signed"}),
    ("manager", {"mine note", "company call", "Signed", "colleague note"}),
    ("admin", {"mine note", "company call", "Signed", "colleague note", "outsider note"}),
])
def test_client_activity_is_scoped(client_for, people, data, who, expected):
    items = client_for(people[who]).get(DASHBOARD).data["client_activity"]
    assert {i["summary"] for i in items} == expected  # "imported" entries are left out
    status = next(i for i in items if i["kind"] == "status")
    assert status["details"] == {"from": "new", "to": "won"} and status["contact"]["name"] == "Mine"


def test_placeholders_stay_for_later_modules(client_for, people):
    data = client_for(people["staff"]).get(DASHBOARD).data
    for key in ("tasks_today", "overdue", "unread_messages"):
        assert data[key] is None
