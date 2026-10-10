import pytest

from apps.contacts.models import Company, Contact
from apps.core.phones import phone_query_variants

pytestmark = pytest.mark.django_db

SEARCH = "/api/v1/search/"


def test_phone_query_variants():
    assert phone_query_variants("0300-1234567") == ["03001234567", "923001234567"]
    assert phone_query_variants("+92 300 123") == ["92300123"]
    assert phone_query_variants("1234") == ["1234"]
    assert phone_query_variants("123") == []  # too short
    assert phone_query_variants("Ali 0300") == []  # not a number


@pytest.fixture
def records(staff, make_user):
    acme = Company.objects.create(name="Acme", phone="042-111 222 333", assigned_to=staff)
    ali = Contact.objects.create(
        first_name="Ali", last_name="Khan", phone="+92 300 1234567", company=acme, status="in_discussion", assigned_to=staff
    )
    Contact.objects.create(first_name="Wa", whatsapp="0321 7654321", assigned_to=staff)
    other = make_user("other@test.com", department="ops", phone="0333 5551234")
    hidden = Contact.objects.create(first_name="Hidden", phone="0300 1234567", assigned_to=other)
    return {"acme": acme, "ali": ali, "other": other, "hidden": hidden}


@pytest.mark.parametrize("query", ["0300-1234567", "03001234567", "+92 300 1234567", "0092 300 1234567", "1234567", "(0300) 123"])
def test_contacts_found_by_phone_in_any_format(client_for, staff, records, query):
    hits = client_for(staff).get(SEARCH, {"q": query}).data["results"].get("contacts", [])
    assert [h["title"] for h in hits] == ["Ali Khan"]  # the hidden duplicate number is not shown


def test_whatsapp_number_and_company_and_people_phones(client_for, staff, records):
    c = client_for(staff)
    assert [h["title"] for h in c.get(SEARCH, {"q": "+923217654321"}).data["results"]["contacts"]] == ["Wa"]
    assert [h["title"] for h in c.get(SEARCH, {"q": "042 111222333"}).data["results"]["companies"]] == ["Acme"]
    assert [h["title"] for h in c.get(SEARCH, {"q": "+92-333-555-1234"}).data["results"]["users"]] == [records["other"].full_name]


def test_contact_hits_show_status_and_company(client_for, staff, records):
    hit = client_for(staff).get(SEARCH, {"q": "Ali"}).data["results"]["contacts"][0]
    assert hit["status"] == "in_discussion" and hit["company"] == "Acme"
    assert hit["subtitle"] == "+92 300 1234567" and hit["url"] == f"/contacts/{records['ali'].pk}"


def test_text_queries_still_work(client_for, staff, records):
    results = client_for(staff).get(SEARCH, {"q": "acm"}).data["results"]
    assert [h["title"] for h in results["companies"]] == ["Acme"]
