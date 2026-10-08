import io

import pytest
from django.core.management import call_command

from apps.contacts.models import Company
from apps.core.models import AuditLog

pytestmark = pytest.mark.django_db

URL = "/api/v1/companies/"


@pytest.fixture
def people(make_user, admin, manager, staff):
    """manager + staff in Sales, a colleague in Sales, an outsider in Operations."""
    return {
        "admin": admin,
        "manager": manager,
        "staff": staff,
        "colleague": make_user("colleague@test.com"),
        "outsider": make_user("ops.person@test.com", department="ops"),
    }


@pytest.fixture
def companies(people):
    def make(name, owner, **extra):
        return Company.objects.create(name=name, assigned_to=people[owner] if owner else None, **extra)

    return {
        "mine": make("Mine Ltd", "staff", city="Lahore", industry="retail"),
        "colleague": make("Colleague Co", "colleague", city="Karachi", industry="finance"),
        "manager": make("Manager Inc", "manager", city="lahore"),
        "outsider": make("Ops Corp", "outsider", city="Multan", industry="logistics"),
        "unassigned": make("Nobody's", None),
    }


def names(res):
    return sorted(c["name"] for c in res.data["results"])


# ---------------------------------------------------------------- model


def test_company_model_defaults_and_str(people):
    company = Company.objects.create(name="Acme")
    assert str(company) == "Acme"
    assert company.industry == "" and company.assigned_to is None
    assert company.created_at and company.updated_at
    assert list(Company.objects.values_list("name", flat=True)) == ["Acme"]


def test_company_ordering_and_industry_label(people):
    Company.objects.create(name="Beta", industry="real_estate")
    Company.objects.create(name="Alpha")
    assert [c.name for c in Company.objects.all()] == ["Alpha", "Beta"]
    assert Company.objects.get(name="Beta").get_industry_display() == "Real estate"


# ---------------------------------------------------------------- visibility by role


def test_scoping_by_role(client_for, people, companies):
    assert names(client_for(people["staff"]).get(URL)) == ["Mine Ltd"]
    assert names(client_for(people["manager"]).get(URL)) == ["Colleague Co", "Manager Inc", "Mine Ltd"]
    assert len(client_for(people["admin"]).get(URL).data["results"]) == 5


def test_staff_cannot_open_or_edit_others(client_for, people, companies):
    c = client_for(people["staff"])
    other = companies["colleague"].pk
    assert c.get(f"{URL}{other}/").status_code == 404
    assert c.patch(f"{URL}{other}/", {"name": "x"}, format="json").status_code == 404
    assert c.get(f"{URL}{companies['mine'].pk}/").status_code == 200


def test_manager_cannot_see_other_departments(client_for, people, companies):
    assert client_for(people["manager"]).get(f"{URL}{companies['outsider'].pk}/").status_code == 404


def test_anonymous_rejected(api, companies):
    assert api.get(URL).status_code == 401


# ---------------------------------------------------------------- create / edit / delete


def test_staff_create_defaults_to_self_and_is_audited(client_for, people):
    c = client_for(people["staff"])
    res = c.post(URL, {"name": "  New Client  ", "city": "Lahore", "website": "newclient.pk"}, format="json")
    assert res.status_code == 201, res.data
    assert res.data["name"] == "New Client"
    assert res.data["assigned_to"] == people["staff"].pk
    assert res.data["website"] == "https://newclient.pk"
    company = Company.objects.get(pk=res.data["id"])
    assert company.created_by == people["staff"] and company.updated_by == people["staff"]
    entry = AuditLog.objects.get(action="create", object_id=str(company.pk))
    assert entry.actor == people["staff"] and entry.changes["name"] == "New Client"


def test_staff_cannot_assign_to_others(client_for, people):
    res = client_for(people["staff"]).post(URL, {"name": "X", "assigned_to": people["colleague"].pk}, format="json")
    assert res.status_code == 400 and "assigned_to" in res.data["errors"]


def test_manager_assigns_within_department_only(client_for, people):
    c = client_for(people["manager"])
    assert c.post(URL, {"name": "A", "assigned_to": people["colleague"].pk}, format="json").status_code == 201
    res = c.post(URL, {"name": "B", "assigned_to": people["outsider"].pk}, format="json")
    assert res.status_code == 400 and "assigned_to" in res.data["errors"]


def test_admin_assigns_anyone(client_for, people):
    res = client_for(people["admin"]).post(URL, {"name": "C", "assigned_to": people["outsider"].pk}, format="json")
    assert res.status_code == 201


def test_cannot_assign_inactive_user(client_for, people, make_user):
    gone = make_user("gone@test.com", is_active=False)
    res = client_for(people["admin"]).post(URL, {"name": "D", "assigned_to": gone.pk}, format="json")
    assert res.status_code == 400


def test_edit_records_updated_by_and_audit_diff(client_for, people, companies):
    company = companies["colleague"]
    res = client_for(people["manager"]).patch(f"{URL}{company.pk}/", {"city": "Islamabad"}, format="json")
    assert res.status_code == 200 and res.data["updated_by_name"] == people["manager"].full_name
    entry = AuditLog.objects.get(action="update", object_id=str(company.pk))
    assert entry.changes == {"city": ["Karachi", "Islamabad"]}


def test_validation_errors(client_for, people):
    c = client_for(people["admin"])
    res = c.post(URL, {"name": "  ", "email": "not-an-email", "industry": "space"}, format="json")
    assert res.status_code == 400
    assert {"name", "email", "industry"} <= set(res.data["errors"])


@pytest.mark.parametrize("role,expected", [("staff", 403), ("manager", 204), ("admin", 204)])
def test_delete_permission_by_role(client_for, people, companies, role, expected):
    target = {"staff": "mine", "manager": "colleague", "admin": "outsider"}[role]
    pk = companies[target].pk
    res = client_for(people[role]).delete(f"{URL}{pk}/")
    assert res.status_code == expected
    if expected == 204:
        assert not Company.objects.filter(pk=pk).exists()
        assert AuditLog.objects.filter(action="delete", object_id=str(pk)).exists()


# ---------------------------------------------------------------- list features


def test_search_filters_and_pagination(client_for, people, companies):
    c = client_for(people["admin"])
    assert names(c.get(URL, {"search": "colleague"})) == ["Colleague Co"]
    assert names(c.get(URL, {"city": "LAHORE"})) == ["Manager Inc", "Mine Ltd"]  # case-insensitive
    assert names(c.get(URL, {"industry": "logistics"})) == ["Ops Corp"]
    assert names(c.get(URL, {"assigned_to": people["staff"].pk})) == ["Mine Ltd"]
    page = c.get(URL, {"page_size": 2})
    assert page.data["count"] == 5 and len(page.data["results"]) == 2 and page.data["next"]


def test_facets_respect_scope(client_for, people, companies):
    assert client_for(people["staff"]).get(f"{URL}facets/").data == {"cities": ["Lahore"]}
    admin_cities = client_for(people["admin"]).get(f"{URL}facets/").data["cities"]
    assert admin_cities == ["Karachi", "Lahore", "Multan"]  # "Lahore" and "lahore" merged


def test_global_search_respects_scope(client_for, people, companies):
    staff_hits = client_for(people["staff"]).get("/api/v1/search/", {"q": "co"}).data["results"]
    assert "companies" not in staff_hits  # "Colleague Co" / "Ops Corp" belong to others
    admin_hits = client_for(people["admin"]).get("/api/v1/search/", {"q": "colleague"}).data["results"]
    assert admin_hits["companies"][0]["url"] == f"/companies/{companies['colleague'].pk}"


def test_industry_label_translated(client_for, people, companies):
    res = client_for(people["admin"]).get(f"{URL}{companies['colleague'].pk}/", HTTP_ACCEPT_LANGUAGE="ur")
    assert res.data["industry"] == "finance" and res.data["industry_label"] == "مالیات"


def test_seed_demo_creates_companies_idempotently():
    call_command("seed_demo", stdout=io.StringIO())
    call_command("seed_demo", stdout=io.StringIO())
    assert Company.objects.count() == 10
    assert not Company.objects.filter(assigned_to__isnull=True).exists()
