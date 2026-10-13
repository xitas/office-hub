"""Message templates: sharing and editing rules, placeholders, wa.me / mailto links, usage and archiving."""
from urllib.parse import unquote

import pytest

from apps.contacts.models import Company, Contact
from apps.message_templates import placeholders
from apps.message_templates.models import MessageTemplate

pytestmark = pytest.mark.django_db

URL = "/api/v1/templates/"


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {
        "admin": admin, "manager": manager, "staff": staff,
        "colleague": make_user("colleague@test.com", full_name="Sara Colleague"),
        "outsider": make_user("ops.person@test.com", department="ops", full_name="Omar Ops"),
        "ops_manager": make_user("ops.manager@test.com", role="manager", department="ops", full_name="Olga Manager"),
    }


def make(owner, name, sharing="personal", **extra):
    return MessageTemplate.objects.create(
        name=name, body=extra.pop("body", "Hello {contact.first_name}"), sharing=sharing, created_by=owner,
        department=owner.department if sharing == "department" else None, **extra,
    )


def names(res):
    return sorted(t["name"] for t in res.data)


# ================================================================ sharing and editing


def test_who_can_share_with_whom(client_for, people, departments):
    staff, manager, admin = (client_for(people[k]) for k in ("staff", "manager", "admin"))
    body = {"name": "Mine", "body": "Hi {contact.first_name}", "category": "general", "channel": "any", "language": "en"}
    assert staff.post(URL, {**body, "sharing": "personal"}).status_code == 201
    assert staff.post(URL, {**body, "sharing": "department"}).status_code == 400
    res = manager.post(URL, {**body, "sharing": "department"})
    assert res.status_code == 201 and res.data["department"] == departments["sales"].pk
    assert manager.post(URL, {**body, "sharing": "everyone"}).status_code == 400
    assert admin.post(URL, {**body, "sharing": "everyone"}).status_code == 201


def test_who_sees_and_changes_templates(client_for, people):
    p = people
    everyone = make(p["admin"], "For everyone", "everyone")
    sales = make(p["colleague"], "Sales dept", "department")  # (a staff member can't create this via the API)
    make(p["outsider"], "Ops dept", "department")
    make(p["colleague"], "Sara's own")
    mine = make(p["staff"], "Staff's own")

    staff = client_for(p["staff"])
    assert names(staff.get(URL)) == ["For everyone", "Sales dept", "Staff's own"]
    assert len(client_for(p["admin"]).get(URL).data) == 5  # admins see and manage all

    assert staff.patch(f"{URL}{mine.pk}/", {"name": "Renamed"}).status_code == 200
    assert staff.patch(f"{URL}{everyone.pk}/", {"name": "x"}).status_code == 403
    assert staff.patch(f"{URL}{sales.pk}/", {"name": "x"}).status_code == 403
    assert client_for(p["manager"]).patch(f"{URL}{sales.pk}/", {"name": "Sales (edited)"}).status_code == 200  # their department
    assert client_for(p["ops_manager"]).patch(f"{URL}{sales.pk}/", {"name": "x"}).status_code == 404  # can't even see it
    assert client_for(p["admin"]).post(f"{URL}{sales.pk}/archive/").data["archived"] is True
    assert staff.post(f"{URL}{everyone.pk}/archive/").status_code == 403
    assert staff.delete(f"{URL}{mine.pk}/").status_code in (403, 405)  # archive, not delete
    assert MessageTemplate.objects.filter(pk=mine.pk).exists()


def test_filters_and_channel_includes_any(client_for, people):
    a = people["admin"]
    make(a, "WA quote", "everyone", channel="whatsapp", category="quotation")
    make(a, "Any thanks", "everyone", channel="any", category="thank_you", language="ur")
    make(a, "Email only", "everyone", channel="email")
    make(people["staff"], "Mine", channel="chat")
    staff = client_for(people["staff"])
    assert names(staff.get(URL, {"channel": "whatsapp"})) == ["Any thanks", "WA quote"]
    assert names(staff.get(URL, {"category": "quotation"})) == ["WA quote"]
    assert names(staff.get(URL, {"language": "ur"})) == ["Any thanks"]
    assert names(staff.get(URL, {"owner": "mine"})) == ["Mine"]
    assert names(staff.get(URL, {"q": "quote"})) == ["WA quote"]


# ================================================================ placeholders


@pytest.fixture
def ali(people):
    acme = Company.objects.create(name="Acme Traders", assigned_to=people["staff"])
    return Contact.objects.create(first_name="Ali", last_name="Khan", company=acme, phone="0300 1234567",
                                  email="ali@acme.pk", assigned_to=people["staff"])


def test_fill_with_a_contact_and_me(client_for, people, ali):
    people["staff"].phone = "0321 7654321"
    people["staff"].save()
    t = make(people["admin"], "Quote", "everyone", subject="Quotation for {contact.company}",
             body="Dear {contact.first_name},\nCall me on {my.phone}. – {my.name} {contact.nickname}")
    res = client_for(people["staff"]).post(f"{URL}{t.pk}/fill/", {"contact": ali.pk}, format="json").data
    assert res["subject"] == "Quotation for Acme Traders"
    assert res["body"] == "Dear Ali,\nCall me on 0321 7654321. – Staff {contact.nickname}"
    assert res["unknown"] == ["contact.nickname"] and res["empty"] == []
    assert res["whatsapp_url"].startswith("https://wa.me/923001234567?text=Dear%20Ali%2C%0ACall%20me")
    assert res["mailto_url"].startswith("mailto:ali@acme.pk?subject=Quotation%20for%20Acme%20Traders&body=Dear%20Ali%2C%0D%0ACall")


def test_missing_values_and_no_contact_are_flagged(client_for, people):
    lone = Contact.objects.create(first_name="Bina", assigned_to=people["staff"])  # no company, phone or email
    t = make(people["admin"], "Hi", "everyone", body="Hi {contact.first_name} from {contact.company}")
    staff = client_for(people["staff"])
    res = staff.post(f"{URL}{t.pk}/fill/", {"contact": lone.pk}, format="json").data
    assert res["body"] == "Hi Bina from " and res["empty"] == ["contact.company"]
    assert res["whatsapp_url"] is None and res["mailto_url"] is None
    res = staff.post(f"{URL}{t.pk}/fill/", {}, format="json").data  # e.g. inserted in chat
    assert res["body"] == "Hi  from " and res["empty"] == ["contact.first_name", "contact.company"]


def test_cannot_fill_with_a_contact_you_cannot_see(client_for, people, ali):
    t = make(people["admin"], "Hi", "everyone")
    assert client_for(people["outsider"]).post(f"{URL}{t.pk}/fill/", {"contact": ali.pk}, format="json").status_code == 404
    assert client_for(people["outsider"]).post(f"{URL}preview/", {"body": "{contact.phone}", "contact": ali.pk}, format="json").status_code == 404


def test_preview_and_placeholder_list(client_for, people, ali):
    staff = client_for(people["staff"])
    res = staff.post(f"{URL}preview/", {"subject": "", "body": "Salaam {contact.first_name} {oops}", "contact": ali.pk}, format="json").data
    assert res["body"] == "Salaam Ali {oops}" and res["unknown"] == ["oops"]
    keys = [p["key"] for p in staff.get(f"{URL}placeholders/").data]
    assert {"contact.first_name", "contact.company", "my.name", "my.phone", "today"} <= set(keys)
    t = make(people["staff"], "Typo", body="Hi {contact.frist_name}")
    assert staff.get(f"{URL}{t.pk}/").data["unknown_placeholders"] == ["contact.frist_name"]


def test_links_encode_urdu_and_line_breaks():
    text = "السلام علیکم علی صاحب،\nقیمت: 5,000 روپے & شکریہ"
    wa = placeholders.whatsapp_link("0300-1234567", text)
    assert wa.startswith("https://wa.me/923001234567?text=")
    encoded = wa.split("text=")[1]
    assert "%0A" in encoded and "&" not in encoded and " " not in encoded and "\n" not in encoded
    assert unquote(encoded) == text
    mail = placeholders.mailto_link("ali@acme.pk", "یاد دہانی", text)
    subject, body = mail.split("?", 1)[1].split("&body=")
    assert unquote(subject.removeprefix("subject=")) == "یاد دہانی"
    assert "%0D%0A" in body and unquote(body) == text.replace("\n", "\r\n")
    assert placeholders.whatsapp_link("", text) is None and placeholders.mailto_link("", "s", "b") is None
    assert placeholders.whatsapp_number("+92 300 1234567") == "923001234567"
    assert placeholders.whatsapp_number("0092 300 1234567") == "923001234567"


# ================================================================ usage, duplicate, archive


def test_usage_count_orders_popular_first(client_for, people):
    a = people["admin"]
    rare, popular = make(a, "Rare", "everyone"), make(a, "Popular", "everyone")
    staff = client_for(people["staff"])
    for _ in range(3):
        staff.post(f"{URL}{popular.pk}/use/")
    res = staff.post(f"{URL}{rare.pk}/use/")
    assert res.data["usage_count"] == 1 and res.data["last_used_at"]
    assert [t["name"] for t in staff.get(URL).data] == ["Popular", "Rare"]


def test_archive_duplicate_and_archived_use(client_for, people):
    original = make(people["admin"], "Thank you", "everyone", category="thank_you", channel="email", subject="Thanks!")
    admin, staff = client_for(people["admin"]), client_for(people["staff"])
    copy = staff.post(f"{URL}{original.pk}/duplicate/")
    assert copy.status_code == 201
    assert (copy.data["name"], copy.data["sharing"], copy.data["created_by"], copy.data["subject"]) == (
        "Thank you (copy)", "personal", people["staff"].pk, "Thanks!")
    admin.post(f"{URL}{original.pk}/archive/")
    assert "Thank you" not in names(staff.get(URL))
    assert "Thank you" in names(staff.get(URL, {"archived": "true"}))
    assert staff.post(f"{URL}{original.pk}/use/").status_code == 403
    assert admin.post(f"{URL}{original.pk}/unarchive/").data["archived"] is False


def test_subject_only_for_email_channels(client_for, people):
    res = client_for(people["staff"]).post(URL, {"name": "Chat hello", "body": "Hi", "channel": "chat", "subject": "Ignored"})
    assert res.status_code == 201 and res.data["subject"] == ""


def test_seed_adds_templates_once(db):
    import io

    from django.core.management import call_command

    call_command("seed_demo", stdout=io.StringIO())
    count = MessageTemplate.objects.count()
    call_command("seed_demo", stdout=io.StringIO())
    assert MessageTemplate.objects.count() == count == 8
    assert MessageTemplate.objects.filter(language="ur").count() == 3
    for t in MessageTemplate.objects.all():
        assert placeholders.check(f"{t.subject}\n{t.body}") == []  # no typos in the demo placeholders
