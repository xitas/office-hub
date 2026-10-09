import io

import pytest
from django.core.management import call_command

from apps.contacts.models import Company, Contact, Tag
from apps.contacts.phones import normalize_phone
from apps.core.models import AuditLog

pytestmark = pytest.mark.django_db

URL = "/api/v1/contacts/"


@pytest.fixture
def people(make_user, admin, manager, staff):
    """manager + staff + colleague in Sales; an outsider in Operations."""
    return {
        "admin": admin,
        "manager": manager,
        "staff": staff,
        "colleague": make_user("colleague@test.com"),
        "outsider": make_user("ops.person@test.com", department="ops"),
    }


@pytest.fixture
def acme(people):
    return Company.objects.create(name="Acme", assigned_to=people["staff"])


@pytest.fixture
def contacts(people, acme):
    def make(first, owner, **extra):
        return Contact.objects.create(first_name=first, last_name="Test", assigned_to=people[owner], **extra)

    return {
        "mine": make("Mine", "staff", company=acme, phone="0300-1234567", email="mine@acme.pk", city="Lahore"),
        "colleague": make("Colleague", "colleague", city="Karachi", status="won", email="col@x.pk"),
        "manager": make("Manager", "manager", city="lahore", status="contacted"),
        "outsider": make("Outsider", "outsider", phone="+92 321 5550000", email="out@ops.pk", status="lost"),
    }


def names(res):
    return sorted(c["first_name"] for c in res.data["results"])


# ---------------------------------------------------------------- model


def test_contact_model_defaults(people):
    c = Contact.objects.create(first_name="Ali", last_name="Khan", phone="0300 123 4567", whatsapp="0092 300 7654321")
    assert c.full_name == str(c) == "Ali Khan"
    assert c.status == "new"
    assert c.phone_digits == "923001234567" and c.whatsapp_digits == "923007654321"


@pytest.mark.parametrize(
    "raw,expected",
    [("0300-1234567", "923001234567"), ("+92 300 1234567", "923001234567"), ("0092 300 1234567", "923001234567"),
     ("", ""), ("(042) 3576-1234", "924235761234")],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


def test_company_delete_keeps_contacts(people, acme, contacts):
    acme.delete()
    contacts["mine"].refresh_from_db()
    assert contacts["mine"].company is None


# ---------------------------------------------------------------- visibility by role


def test_scoping_by_role(client_for, people, contacts):
    assert names(client_for(people["staff"]).get(URL)) == ["Mine"]
    assert names(client_for(people["manager"]).get(URL)) == ["Colleague", "Manager", "Mine"]
    assert len(client_for(people["admin"]).get(URL).data["results"]) == 4


def test_staff_cannot_open_others(client_for, people, contacts):
    c = client_for(people["staff"])
    assert c.get(f"{URL}{contacts['colleague'].pk}/").status_code == 404
    assert c.patch(f"{URL}{contacts['colleague'].pk}/", {"status": "won"}, format="json").status_code == 404


@pytest.mark.parametrize("role,expected", [("staff", 403), ("manager", 204), ("admin", 204)])
def test_delete_permission_by_role(client_for, people, contacts, role, expected):
    target = {"staff": "mine", "manager": "colleague", "admin": "outsider"}[role]
    pk = contacts[target].pk
    assert client_for(people[role]).delete(f"{URL}{pk}/").status_code == expected
    if expected == 204:
        assert AuditLog.objects.filter(action="delete", object_id=str(pk)).exists()


# ---------------------------------------------------------------- create / edit


def test_create_with_tags_defaults_and_audit(client_for, people, acme):
    c = client_for(people["staff"])
    res = c.post(
        URL,
        {"first_name": " Sara ", "last_name": "Ali", "company": acme.pk, "tags": ["VIP", " vip ", "Follow  up"]},
        format="json",
    )
    assert res.status_code == 201, res.data
    assert res.data["full_name"] == "Sara Ali" and res.data["status"] == "new"
    assert res.data["assigned_to"] == people["staff"].pk and res.data["company_name"] == "Acme"
    assert res.data["tags"] == ["Follow up", "VIP"]  # de-duplicated ignoring case, whitespace tidied
    assert res.data["duplicates"] == []
    entry = AuditLog.objects.get(action="create", object_id=str(res.data["id"]))
    assert entry.changes["tags"] == "Follow up, VIP" and "phone_digits" not in entry.changes


def test_tags_are_reused_ignoring_case(client_for, people):
    Tag.objects.create(name="Key account")
    c = client_for(people["staff"])
    c.post(URL, {"first_name": "A", "tags": ["key ACCOUNT"]}, format="json")
    assert Tag.objects.count() == 1


def test_status_and_tag_changes_are_audited(client_for, people, contacts):
    pk = contacts["mine"].pk
    res = client_for(people["staff"]).patch(f"{URL}{pk}/", {"status": "in_discussion", "tags": ["Hot"]}, format="json")
    assert res.status_code == 200 and res.data["status_label"] == "In discussion"
    entry = AuditLog.objects.get(action="update", object_id=str(pk))
    assert entry.changes == {"status": ["new", "in_discussion"], "tags": ["", "Hot"]}


def test_edit_without_tags_field_keeps_tags(client_for, people, contacts):
    contacts["mine"].tags.add(Tag.objects.create(name="Keep"))
    res = client_for(people["staff"]).patch(f"{URL}{contacts['mine'].pk}/", {"city": "Multan"}, format="json")
    assert res.data["tags"] == ["Keep"]


def test_assignment_rules(client_for, people):
    staff, manager = client_for(people["staff"]), client_for(people["manager"])
    assert staff.post(URL, {"first_name": "X", "assigned_to": people["colleague"].pk}, format="json").status_code == 400
    assert manager.post(URL, {"first_name": "X", "assigned_to": people["colleague"].pk}, format="json").status_code == 201
    assert manager.post(URL, {"first_name": "X", "assigned_to": people["outsider"].pk}, format="json").status_code == 400
    assert client_for(people["admin"]).post(
        URL, {"first_name": "X", "assigned_to": people["outsider"].pk}, format="json"
    ).status_code == 201


def test_cannot_link_company_user_cannot_see(client_for, people):
    hidden = Company.objects.create(name="Hidden", assigned_to=people["outsider"])
    res = client_for(people["staff"]).post(URL, {"first_name": "X", "company": hidden.pk}, format="json")
    assert res.status_code == 400 and "company" in res.data["errors"]


def test_validation(client_for, people):
    res = client_for(people["staff"]).post(URL, {"first_name": "  ", "email": "bad", "status": "maybe"}, format="json")
    assert res.status_code == 400 and {"first_name", "email", "status"} <= set(res.data["errors"])


# ---------------------------------------------------------------- duplicates


def test_duplicate_warning_on_create_does_not_block(client_for, people, contacts):
    c = client_for(people["staff"])
    res = c.post(URL, {"first_name": "Again", "phone": "+92 300 1234567", "email": "MINE@acme.pk"}, format="json")
    assert res.status_code == 201
    [dup] = res.data["duplicates"]
    assert dup["id"] == contacts["mine"].pk and dup["visible"] and sorted(dup["matched"]) == ["email", "phone"]


def test_duplicate_warning_on_edit_excludes_self(client_for, people, contacts):
    pk = contacts["mine"].pk
    res = client_for(people["staff"]).patch(f"{URL}{pk}/", {"city": "Lahore"}, format="json")
    assert res.data["duplicates"] == []


def test_duplicate_matches_whatsapp_number(client_for, people, contacts):
    res = client_for(people["admin"]).get(f"{URL}duplicates/", {"whatsapp": "03001234567"})
    assert [d["id"] for d in res.data["duplicates"]] == [contacts["mine"].pk]


def test_duplicate_of_hidden_contact_reveals_no_details(client_for, people, contacts):
    res = client_for(people["staff"]).get(f"{URL}duplicates/", {"email": "out@ops.pk"})
    [dup] = res.data["duplicates"]
    assert dup == {
        "id": None, "name": None, "company_name": None,
        "assigned_to_name": people["outsider"].full_name, "matched": ["email"], "visible": False,
    }


def test_duplicate_check_ignores_short_or_empty_input(client_for, people, contacts):
    c = client_for(people["admin"])
    assert c.get(f"{URL}duplicates/", {"phone": "03"}).data["duplicates"] == []
    assert c.get(f"{URL}duplicates/").data["duplicates"] == []


# ---------------------------------------------------------------- list, filters, search


def test_search_by_name_phone_and_email(client_for, people, contacts):
    c = client_for(people["admin"])
    assert names(c.get(URL, {"search": "outsider"})) == ["Outsider"]
    assert names(c.get(URL, {"search": "1234567"})) == ["Mine"]
    assert names(c.get(URL, {"search": "923215550000"})) == ["Outsider"]  # matches the normalised number
    assert names(c.get(URL, {"search": "col@x"})) == ["Colleague"]
    assert names(c.get(URL, {"search": "Mine Test"})) == ["Mine"]


def test_filters(client_for, people, contacts, acme):
    contacts["mine"].tags.add(Tag.objects.create(name="VIP"))
    c = client_for(people["admin"])
    assert names(c.get(URL, {"company": acme.pk})) == ["Mine"]
    assert names(c.get(URL, {"city": "LAHORE"})) == ["Manager", "Mine"]
    assert names(c.get(URL, {"tag": "vip"})) == ["Mine"]
    assert names(c.get(URL, {"status": "won"})) == ["Colleague"]
    assert names(c.get(URL, {"assigned_to": people["outsider"].pk})) == ["Outsider"]
    page = c.get(URL, {"page_size": 2})
    assert page.data["count"] == 4 and len(page.data["results"]) == 2


def test_facets_and_tag_suggestions(client_for, people, contacts):
    contacts["mine"].tags.add(Tag.objects.create(name="VIP"))
    contacts["outsider"].tags.add(Tag.objects.create(name="Secret"))
    staff = client_for(people["staff"])
    assert staff.get(f"{URL}facets/").data == {"cities": ["Lahore"], "tags": ["VIP"]}
    assert [t["name"] for t in staff.get("/api/v1/tags/", {"search": "vi"}).data] == ["VIP"]


def test_global_search_contacts_respects_scope(client_for, people, contacts):
    staff_hits = client_for(people["staff"]).get("/api/v1/search/", {"q": "outsider"}).data["results"]
    assert "contacts" not in staff_hits
    admin_hits = client_for(people["admin"]).get("/api/v1/search/", {"q": "outsider"}).data["results"]
    assert admin_hits["contacts"][0]["url"] == f"/contacts/{contacts['outsider'].pk}"


def test_status_label_translated(client_for, people, contacts):
    res = client_for(people["admin"]).get(f"{URL}{contacts['colleague'].pk}/", HTTP_ACCEPT_LANGUAGE="ur")
    assert res.data["status"] == "won" and res.data["status_label"] == "کامیاب"


def test_seed_demo_contacts():
    call_command("seed_demo", stdout=io.StringIO())
    call_command("seed_demo", stdout=io.StringIO())  # idempotent
    assert Contact.objects.count() == 40
    assert Contact.objects.values("company").distinct().count() == 10
    assert set(Contact.objects.values_list("status", flat=True)) == {"new", "contacted", "in_discussion", "won", "lost"}
    assert Contact.objects.filter(tags__isnull=False).distinct().count() > 20
    assert not Contact.objects.filter(assigned_to__isnull=True).exists()
