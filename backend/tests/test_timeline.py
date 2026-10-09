from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.contacts.models import Company, Contact
from apps.core.models import AuditLog
from apps.timeline.models import TimelineEntry
from apps.timeline.registry import EntryType, auto_entry, register_provider, register_type

pytestmark = pytest.mark.django_db

TIMELINE = "/api/v1/timeline/"
CONTACTS = "/api/v1/contacts/"


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {
        "admin": admin,
        "manager": manager,  # Sales manager
        "staff": staff,  # Sales
        "colleague": make_user("colleague@test.com"),  # Sales
        "outsider": make_user("ops.person@test.com", department="ops"),
        "ops_manager": make_user("ops.manager@test.com", role="manager", department="ops"),
    }


@pytest.fixture
def records(people):
    acme = Company.objects.create(name="Acme", assigned_to=people["staff"])
    return {
        "acme": acme,
        "mine": Contact.objects.create(first_name="Ali", last_name="Khan", company=acme, assigned_to=people["staff"]),
        # At the staff member's company, but assigned to someone else: hidden from staff.
        "colleague": Contact.objects.create(first_name="Sara", company=acme, assigned_to=people["colleague"]),
        "outsider": Contact.objects.create(first_name="Omar", assigned_to=people["outsider"]),
    }


def note(user, summary="Called about the quote", **target):
    return TimelineEntry.objects.create(kind="note", summary=summary, created_by=user, **target)


def ids(res, kind=None):
    return [e["summary"] for e in res.data["results"] if kind is None or e["kind"] == kind]


# ---------------------------------------------------------------- model


def test_entry_needs_exactly_one_target(people, records):
    with pytest.raises(IntegrityError), transaction.atomic():
        TimelineEntry.objects.create(kind="note", summary="x")
    with pytest.raises(IntegrityError), transaction.atomic():
        TimelineEntry.objects.create(kind="note", summary="x", contact=records["mine"], company=records["acme"])
    entry = note(people["staff"], contact=records["mine"])
    assert entry.target == records["mine"]
    assert abs(entry.occurred_at - timezone.now()) < timedelta(seconds=5)


def test_entries_go_with_their_record(people, records):
    note(people["staff"], contact=records["mine"])
    records["mine"].delete()
    assert not TimelineEntry.objects.exists()


# ---------------------------------------------------------------- create + validation


def test_staff_logs_a_note_on_own_contact(client_for, people, records):
    res = client_for(people["staff"]).post(
        TIMELINE, {"kind": "note", "contact": records["mine"].pk, "summary": "  Wants a demo  ", "follow_up_on": "2026-11-01"},
        format="json",
    )
    assert res.status_code == 201, res.data
    assert res.data["summary"] == "Wants a demo"
    assert res.data["created_by_name"] == people["staff"].full_name
    assert res.data["editable"] is True
    assert res.data["contact"] == {"id": records["mine"].pk, "name": "Ali Khan"}
    entry = TimelineEntry.objects.get()
    assert entry.created_by == people["staff"] and str(entry.follow_up_on) == "2026-11-01"
    assert AuditLog.objects.filter(action=AuditLog.Action.CREATE, object_id=str(entry.pk)).exists()


def test_call_details_are_validated(client_for, people, records):
    c = client_for(people["staff"])
    ok = c.post(TIMELINE, {
        "kind": "call", "contact": records["mine"].pk, "summary": "",
        "details": {"direction": "out", "outcome": "no_answer", "duration_minutes": None, "junk": 1},
    }, format="json")
    assert ok.status_code == 201, ok.data
    assert ok.data["details"] == {"direction": "out", "outcome": "no_answer"}  # empty and unknown keys dropped

    bad = c.post(TIMELINE, {"kind": "call", "contact": records["mine"].pk, "details": {"direction": "sideways"}}, format="json")
    assert bad.status_code == 400 and set(bad.data["errors"]["details"]) == {"direction", "outcome"}


def test_meeting_can_be_backdated_but_not_future(client_for, people, records):
    c = client_for(people["staff"])
    past = (timezone.now() - timedelta(days=3)).isoformat()
    res = c.post(TIMELINE, {
        "kind": "meeting", "company": records["acme"].pk, "occurred_at": past,
        "details": {"location": "Their office, Gulberg", "attendees": "Ali, Sara"},
    }, format="json")
    assert res.status_code == 201, res.data
    assert TimelineEntry.objects.get().occurred_at < timezone.now() - timedelta(days=2)

    future = (timezone.now() + timedelta(days=1)).isoformat()
    res = c.post(TIMELINE, {"kind": "meeting", "company": records["acme"].pk, "occurred_at": future}, format="json")
    assert res.status_code == 400 and "occurred_at" in res.data["errors"]


@pytest.mark.parametrize("payload", [
    {"kind": "note", "summary": "no target"},
    {"kind": "note", "summary": "   "},  # target added below; blank note
    {"kind": "status", "summary": "automatic kinds can't be created"},
    {"kind": "whatever", "summary": "x"},
])
def test_invalid_entries_rejected(client_for, people, records, payload):
    if payload["summary"].strip() != "no target":
        payload = {**payload, "contact": records["mine"].pk}
    res = client_for(people["staff"]).post(TIMELINE, payload, format="json")
    assert res.status_code == 400
    assert not TimelineEntry.objects.exists()


def test_both_targets_rejected(client_for, people, records):
    res = client_for(people["staff"]).post(
        TIMELINE, {"kind": "note", "summary": "x", "contact": records["mine"].pk, "company": records["acme"].pk}, format="json"
    )
    assert res.status_code == 400


# ---------------------------------------------------------------- visibility per role


@pytest.mark.parametrize("who,target,allowed", [
    ("staff", "mine", True),
    ("staff", "colleague", False),
    ("staff", "outsider", False),
    ("manager", "colleague", True),  # same department
    ("manager", "outsider", False),
    ("ops_manager", "outsider", True),
    ("admin", "outsider", True),
])
def test_add_and_read_only_on_visible_contacts(client_for, people, records, who, target, allowed):
    c = client_for(people[who])
    contact = records[target]
    res = c.post(TIMELINE, {"kind": "note", "contact": contact.pk, "summary": "hello"}, format="json")
    assert res.status_code == (201 if allowed else 400)
    note(people["admin"], "existing", contact=contact)
    listing = c.get(TIMELINE, {"contact": contact.pk})
    assert listing.status_code == (200 if allowed else 404)
    if allowed:
        assert "existing" in ids(listing)


def test_company_visibility(client_for, people, records):
    note(people["staff"], "company note", company=records["acme"])
    assert client_for(people["outsider"]).get(TIMELINE, {"company": records["acme"].pk}).status_code == 404
    res = client_for(people["outsider"]).post(
        TIMELINE, {"kind": "note", "company": records["acme"].pk, "summary": "x"}, format="json"
    )
    assert res.status_code == 400
    assert ids(client_for(people["manager"]).get(TIMELINE, {"company": records["acme"].pk}), "note") == ["company note"]


def test_list_needs_one_target(client_for, people, records):
    c = client_for(people["admin"])
    assert c.get(TIMELINE).status_code == 400
    assert c.get(TIMELINE, {"contact": records["mine"].pk, "company": records["acme"].pk}).status_code == 400
    assert c.get(TIMELINE, {"contact": "abc"}).status_code == 400


# ---------------------------------------------------------------- edit / delete rules


@pytest.mark.parametrize("who,allowed", [
    ("staff", True),  # author
    ("colleague", False),  # same department and can see the contact, but not the author
    ("manager", True),  # manager of the author's department
    ("ops_manager", False),  # a manager of another department
    ("admin", True),
])
def test_edit_rules(client_for, people, records, who, allowed):
    # Put the entry on a contact everyone involved can see, so only the edit rule is tested.
    shared = Contact.objects.create(first_name="Shared", assigned_to=people[who] if who != "admin" else people["staff"])
    entry = note(people["staff"], contact=shared)
    res = client_for(people[who]).patch(f"{TIMELINE}{entry.pk}/", {"summary": "Updated"}, format="json")
    assert res.status_code == (200 if allowed else 403), res.data
    entry.refresh_from_db()
    assert (entry.summary == "Updated") is allowed
    if allowed:
        assert entry.updated_by == people[who]
        log = AuditLog.objects.get(action=AuditLog.Action.UPDATE, object_id=str(entry.pk))
        assert log.changes["summary"] == ["Called about the quote", "Updated"]


@pytest.mark.parametrize("who,allowed", [
    ("staff", True), ("colleague", False), ("manager", True), ("ops_manager", False), ("admin", True),
])
def test_delete_rules(client_for, people, records, who, allowed):
    shared = Contact.objects.create(first_name="Shared", assigned_to=people[who] if who != "admin" else people["staff"])
    entry = note(people["staff"], contact=shared)
    res = client_for(people[who]).delete(f"{TIMELINE}{entry.pk}/")
    assert res.status_code == (204 if allowed else 403)
    assert TimelineEntry.objects.filter(pk=entry.pk).exists() is not allowed
    assert AuditLog.objects.filter(action=AuditLog.Action.DELETE, object_id=str(entry.pk)).exists() is allowed


def test_cannot_touch_entries_on_hidden_records(client_for, people, records):
    entry = note(people["outsider"], contact=records["outsider"])
    c = client_for(people["manager"])
    assert c.patch(f"{TIMELINE}{entry.pk}/", {"summary": "x"}, format="json").status_code == 404
    assert c.delete(f"{TIMELINE}{entry.pk}/").status_code == 404


def test_type_and_target_are_fixed(client_for, people, records):
    entry = note(people["staff"], contact=records["mine"])
    c = client_for(people["staff"])
    assert c.patch(f"{TIMELINE}{entry.pk}/", {"kind": "call"}, format="json").status_code == 400
    assert c.patch(f"{TIMELINE}{entry.pk}/", {"contact": records["colleague"].pk}, format="json").status_code == 400
    assert c.patch(f"{TIMELINE}{entry.pk}/", {"company": records["acme"].pk}, format="json").status_code == 400


def test_editable_flag(client_for, people, records):
    note(people["colleague"], "by colleague", contact=records["mine"])
    note(people["staff"], "by me", contact=records["mine"])
    res = client_for(people["staff"]).get(TIMELINE, {"contact": records["mine"].pk, "type": "note"})
    assert {e["summary"]: e["editable"] for e in res.data["results"]} == {"by me": True, "by colleague": False}


# ---------------------------------------------------------------- company roll-up


def test_company_timeline_includes_visible_contacts_entries(client_for, people, records):
    note(people["staff"], "on company", company=records["acme"])
    note(people["staff"], "on Ali", contact=records["mine"])
    note(people["colleague"], "on Sara", contact=records["colleague"])
    note(people["outsider"], "unrelated", contact=records["outsider"])

    staff_view = client_for(people["staff"]).get(TIMELINE, {"company": records["acme"].pk, "type": "note"})
    assert sorted(ids(staff_view)) == ["on Ali", "on company"]  # Sara's contact is hidden from staff
    ali = next(e for e in staff_view.data["results"] if e["summary"] == "on Ali")
    assert ali["contact"]["name"] == "Ali Khan" and ali["company"] is None

    manager_view = client_for(people["manager"]).get(TIMELINE, {"company": records["acme"].pk, "type": "note"})
    assert sorted(ids(manager_view)) == ["on Ali", "on Sara", "on company"]

    # A contact's own timeline doesn't pull in the company's entries.
    assert ids(client_for(people["staff"]).get(TIMELINE, {"contact": records["mine"].pk, "type": "note"})) == ["on Ali"]


# ---------------------------------------------------------------- automatic entries, ordering, filters


def test_automatic_entries_for_creation_and_status_changes(client_for, people):
    c = client_for(people["staff"])
    contact_id = c.post(CONTACTS, {"first_name": "Bilal", "status": "new"}, format="json").data["id"]
    c.patch(f"{CONTACTS}{contact_id}/", {"status": "won", "status_reason": "Signed the contract"}, format="json")
    c.post(TIMELINE, {"kind": "note", "contact": contact_id, "summary": "Kick-off next week"}, format="json")

    res = c.get(TIMELINE, {"contact": contact_id})
    assert [e["kind"] for e in res.data["results"]] == ["note", "status", "created"]
    status, created = res.data["results"][1:]
    assert status["details"] == {"from": "new", "to": "won"}
    assert status["summary"] == "Signed the contract"
    assert status["created_by_name"] == people["staff"].full_name and status["editable"] is False
    assert created["details"] == {"record": "contact", "status": "new"}

    company_id = c.post("/api/v1/companies/", {"name": "Bolan Traders"}, format="json").data["id"]
    res = c.get(TIMELINE, {"company": company_id})
    assert [(e["kind"], e["details"]) for e in res.data["results"]] == [("created", {"record": "company"})]


def test_newest_first_and_type_filter(client_for, people, records):
    now = timezone.now()
    for days, kind, text in [(5, "note", "old"), (1, "call", "recent"), (3, "meeting", "middle")]:
        TimelineEntry.objects.create(
            kind=kind, summary=text, contact=records["mine"], created_by=people["staff"], occurred_at=now - timedelta(days=days)
        )
    c = client_for(people["staff"])
    assert ids(c.get(TIMELINE, {"contact": records["mine"].pk, "type": "note,call,meeting"})) == ["recent", "middle", "old"]
    assert ids(c.get(TIMELINE, {"contact": records["mine"].pk, "type": "call"})) == ["recent"]
    kinds = [e["kind"] for e in c.get(TIMELINE, {"contact": records["mine"].pk, "type": "created"}).data["results"]]
    assert kinds == ["created"]


def test_pagination(client_for, people, records):
    TimelineEntry.objects.bulk_create([
        TimelineEntry(kind="note", summary=f"n{i}", contact=records["mine"], created_by=people["staff"]) for i in range(30)
    ])
    res = client_for(people["staff"]).get(TIMELINE, {"contact": records["mine"].pk})
    assert res.data["count"] == 31  # 30 notes + "created"
    assert len(res.data["results"]) == 25 and res.data["next"]


def test_new_types_and_providers_plug_in(client_for, people, records, monkeypatch):
    from apps.timeline import registry

    monkeypatch.setattr(registry, "_types", dict(registry._types))
    monkeypatch.setattr(registry, "_providers", dict(registry._providers))
    register_type(EntryType("whatsapp", "WhatsApp"))
    register_provider("task", lambda user, contact_ids, company_ids: [
        auto_entry(uid="task:1", kind="task", occurred_at=timezone.now(), summary="Send brochure", contact=records["mine"])
    ] if records["mine"].pk in contact_ids else [])

    c = client_for(people["staff"])
    assert c.post(TIMELINE, {"kind": "whatsapp", "contact": records["mine"].pk, "summary": "Sent price list"}, format="json").status_code == 201
    kinds = {e["kind"] for e in c.get(TIMELINE, {"contact": records["mine"].pk}).data["results"]}
    assert kinds == {"whatsapp", "task", "created"}


# ---------------------------------------------------------------- language, seed


def test_errors_follow_reader_language(client_for, people, records):
    res = client_for(people["staff"]).post(
        TIMELINE, {"kind": "note", "contact": records["mine"].pk, "summary": " "}, format="json", HTTP_ACCEPT_LANGUAGE="ur"
    )
    assert res.data["errors"]["summary"] == ["براہ کرم کچھ لکھیں۔"]


def test_seed_adds_timeline_once(db):
    import io

    from django.core.management import call_command

    call_command("seed_demo", stdout=io.StringIO())
    count = TimelineEntry.objects.count()
    call_command("seed_demo", stdout=io.StringIO())  # idempotent
    assert TimelineEntry.objects.count() == count
    assert TimelineEntry.objects.filter(company__isnull=False).exists()
    assert set(TimelineEntry.objects.values_list("kind", flat=True)) == {"note", "call", "meeting"}
    now = timezone.now()
    for entry in TimelineEntry.objects.select_related("contact", "company"):
        assert entry.target.created_at < entry.occurred_at < now
        assert entry.created_by_id == entry.target.assigned_to_id
