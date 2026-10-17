"""Communication log: email and WhatsApp entries, the log page (scoping, filters, CSV export),
automatic follow-up tasks, "last contacted" dates and the "My follow-ups due" widget."""
from datetime import datetime, timedelta, timezone as dt_timezone

import pytest
from django.utils import timezone

from apps.contacts.models import Company, Contact
from apps.core.models import AuditLog, OrganizationSettings
from apps.core.office_time import office_today
from apps.tasks.models import Task
from apps.timeline.models import TimelineEntry

pytestmark = pytest.mark.django_db

TIMELINE = "/api/v1/timeline/"
LOG = "/api/v1/timeline/log/"


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {
        "admin": admin, "manager": manager, "staff": staff,
        "colleague": make_user("colleague@test.com", full_name="Sara Colleague"),
        "outsider": make_user("ops.person@test.com", department="ops", full_name="Omar Ops"),
    }


@pytest.fixture
def crm(people):
    acme = Company.objects.create(name="Acme Traders", assigned_to=people["staff"])
    ali = Contact.objects.create(first_name="Ali", last_name="Khan", company=acme, assigned_to=people["staff"])
    sara = Contact.objects.create(first_name="Sara", last_name="Malik", assigned_to=people["colleague"])
    ops = Contact.objects.create(first_name="Omar", last_name="Field", assigned_to=people["outsider"])
    return {"acme": acme, "ali": ali, "sara": sara, "ops": ops}


def log(client, kind, target, summary="", **extra):
    body = {"kind": kind, "summary": summary, **target, **extra}
    res = client.post(TIMELINE, body, format="json")
    assert res.status_code == 201, res.data
    return TimelineEntry.objects.get(pk=res.data["entry_id"])


def ago(days, hours=0):
    return (timezone.now() - timedelta(days=days, hours=hours)).isoformat()


# ================================================================ email and WhatsApp entries


def test_email_and_whatsapp_entries(client_for, people, crm):
    c = client_for(people["staff"])
    email = log(c, "email", {"contact": crm["ali"].pk}, "Sent the price list", details={"direction": "out", "subject": "Price list"})
    assert email.details == {"direction": "out", "subject": "Price list"}
    wa = log(c, "whatsapp", {"company": crm["acme"].pk}, "Asked about delivery", details={"direction": "in"})
    assert wa.details == {"direction": "in"}
    bad = c.post(TIMELINE, {"kind": "whatsapp", "contact": crm["ali"].pk, "summary": "x", "details": {"direction": "sideways"}}, format="json")
    assert bad.status_code == 400 and "details" in bad.data["errors"]
    empty = c.post(TIMELINE, {"kind": "email", "contact": crm["ali"].pk, "summary": "", "details": {"direction": "out"}}, format="json")
    assert empty.status_code == 400  # what was said is needed
    kinds = {e["kind"] for e in c.get(TIMELINE, {"contact": crm["ali"].pk}).data["results"]}
    assert {"email"} <= kinds


# ================================================================ log page: scoping and filters


@pytest.fixture
def entries(client_for, people, crm):
    staff, colleague, outsider = (client_for(people[k]) for k in ("staff", "colleague", "outsider"))
    return {
        "call": log(staff, "call", {"contact": crm["ali"].pk}, "Discussed order", details={"direction": "out", "outcome": "connected"}, occurred_at=ago(1)),
        "email_in": log(staff, "email", {"company": crm["acme"].pk}, "They want a quote", details={"direction": "in", "subject": "Quote"}, occurred_at=ago(3)),
        "note": log(staff, "note", {"contact": crm["ali"].pk}, "Prefers mornings", occurred_at=ago(10), follow_up_on=str(office_today() + timedelta(days=2))),
        "colleague_wa": log(colleague, "whatsapp", {"contact": crm["sara"].pk}, "Sent catalogue", details={"direction": "out"}, occurred_at=ago(2)),
        "ops_meeting": log(outsider, "meeting", {"contact": crm["ops"].pk}, "Site visit", occurred_at=ago(4)),
    }


def ids(res):
    return {e["entry_id"] for e in res.data["results"]}


def test_log_is_scoped_per_role(client_for, people, entries):
    e = entries
    assert ids(client_for(people["staff"]).get(LOG)) == {e["call"].pk, e["email_in"].pk, e["note"].pk}
    assert ids(client_for(people["manager"]).get(LOG)) == {e["call"].pk, e["email_in"].pk, e["note"].pk, e["colleague_wa"].pk}
    assert ids(client_for(people["admin"]).get(LOG)) == {x.pk for x in e.values()}
    newest_first = [x["entry_id"] for x in client_for(people["admin"]).get(LOG).data["results"]]
    assert newest_first == [e["call"].pk, e["colleague_wa"].pk, e["email_in"].pk, e["ops_meeting"].pk, e["note"].pk]


def test_log_filters(client_for, people, crm, entries):
    e, admin = entries, client_for(people["admin"])
    f = lambda **p: ids(admin.get(LOG, p))  # noqa: E731
    assert f(type="email,whatsapp") == {e["email_in"].pk, e["colleague_wa"].pk}
    assert f(direction="in") == {e["email_in"].pk}
    assert f(logged_by=people["colleague"].pk) == {e["colleague_wa"].pk}
    assert f(contact=crm["ali"].pk) == {e["call"].pk, e["note"].pk}
    assert f(company=crm["acme"].pk) == {e["call"].pk, e["email_in"].pk, e["note"].pk}  # the company and its contacts
    today = office_today()
    assert f(date_from=str(today - timedelta(days=2)), date_to=str(today)) == {e["call"].pk, e["colleague_wa"].pk}
    assert f(follow_up="any") == f(has_follow_up="true") == {e["note"].pk}
    assert f(follow_up="none") == {x.pk for x in e.values()} - {e["note"].pk}
    assert f(q="catalogue") == {e["colleague_wa"].pk}
    assert f(q="quote") == {e["email_in"].pk}  # subject or summary
    assert admin.get(LOG, {"type": "status"}).status_code == 400
    assert admin.get(LOG, {"date_from": "yesterday"}).status_code == 400


# ================================================================ automatic follow-up tasks


def test_follow_up_creates_a_task_for_the_logger(client_for, people, crm):
    due = office_today() + timedelta(days=3)
    entry = log(client_for(people["staff"]), "call", {"contact": crm["ali"].pk}, "Wants a revised quote\nmore detail",
                details={"direction": "out", "outcome": "connected"}, follow_up_on=str(due))
    task = Task.objects.get(follow_up_of=entry)
    assert task.title == "Follow up with Ali Khan: Wants a revised quote"
    assert (task.due_date, task.contact, task.created_by) == (due, crm["ali"], people["staff"])
    assert list(task.assignees.all()) == [people["staff"]]
    item = next(i for i in client_for(people["staff"]).get(TIMELINE, {"contact": crm["ali"].pk}).data["results"] if i["entry_id"] == entry.pk)
    assert item["follow_up_task"] == {"id": task.pk, "status": "todo", "assignees": ["Staff"]}
    assert item["follow_up_done"] is False and item["follow_up_skipped"] is False


def test_follow_up_can_go_to_a_colleague_or_be_skipped(client_for, people, crm):
    staff = client_for(people["staff"])
    due = str(office_today() + timedelta(days=1))
    to_colleague = log(staff, "email", {"contact": crm["ali"].pk}, "Quote sent", details={"direction": "out"},
                       follow_up_on=due, follow_up_assignee=people["colleague"].pk)
    assert list(Task.objects.get(follow_up_of=to_colleague).assignees.all()) == [people["colleague"]]

    refused = staff.post(TIMELINE, {"kind": "note", "contact": crm["ali"].pk, "summary": "x", "follow_up_on": due,
                                    "follow_up_assignee": people["outsider"].pk}, format="json")
    assert refused.status_code == 400 and "follow_up_assignee" in refused.data["errors"]
    assert not TimelineEntry.objects.filter(summary="x").exists()  # nothing half-saved

    skipped = log(staff, "note", {"contact": crm["ali"].pk}, "Maybe later", follow_up_on=due, follow_up_skip=True)
    skipped.refresh_from_db()
    assert skipped.follow_up_skipped and not Task.objects.filter(follow_up_of=skipped).exists()
    # Editing the text keeps it skipped; choosing a new date makes the task after all.
    staff.patch(f"{TIMELINE}{skipped.pk}/", {"summary": "Maybe later, call Friday"}, format="json")
    assert not Task.objects.filter(follow_up_of=skipped).exists()
    staff.patch(f"{TIMELINE}{skipped.pk}/", {"follow_up_on": str(office_today() + timedelta(days=5))}, format="json")
    assert Task.objects.filter(follow_up_of=skipped).exists()


def test_completing_the_task_marks_the_follow_up_done(client_for, people, crm):
    staff = client_for(people["staff"])
    entry = log(staff, "call", {"contact": crm["ali"].pk}, "Call back", details={"direction": "out", "outcome": "no_answer"},
                follow_up_on=str(office_today() + timedelta(days=1)))
    task = Task.objects.get(follow_up_of=entry)
    # Moving the follow-up date moves the open task.
    new_due = office_today() + timedelta(days=4)
    staff.patch(f"{TIMELINE}{entry.pk}/", {"follow_up_on": str(new_due)}, format="json")
    task.refresh_from_db()
    assert task.due_date == new_due and Task.objects.filter(follow_up_of=entry).count() == 1

    assert staff.patch(f"/api/v1/tasks/{task.pk}/", {"status": "done"}, format="json").status_code == 200
    entry.refresh_from_db()
    assert entry.follow_up_done_at is not None
    assert ids(staff.get(LOG, {"follow_up": "done"})) == {entry.pk}
    staff.patch(f"/api/v1/tasks/{task.pk}/", {"status": "in_progress"}, format="json")
    entry.refresh_from_db()
    assert entry.follow_up_done_at is None


# ================================================================ last contacted


def test_last_contacted_dates(client_for, people, crm):
    staff = client_for(people["staff"])
    assert staff.get(f"/api/v1/contacts/{crm['ali'].pk}/").data["last_contacted_at"] is None
    log(staff, "note", {"contact": crm["ali"].pk}, "Internal note", occurred_at=ago(0, 1))  # a note isn't contact
    call = log(staff, "call", {"contact": crm["ali"].pk}, "", details={"direction": "out", "outcome": "busy"}, occurred_at=ago(5))
    log(staff, "whatsapp", {"contact": crm["ali"].pk}, "Old", details={"direction": "in"}, occurred_at=ago(9))
    got = staff.get(f"/api/v1/contacts/{crm['ali'].pk}/").data["last_contacted_at"]
    assert datetime.fromisoformat(got).astimezone(dt_timezone.utc) == call.occurred_at.astimezone(dt_timezone.utc)
    # A company: its own entries and its contacts'.
    company = staff.get(f"/api/v1/companies/{crm['acme'].pk}/").data["last_contacted_at"]
    assert datetime.fromisoformat(company).astimezone(dt_timezone.utc) == call.occurred_at.astimezone(dt_timezone.utc)
    newer = log(staff, "email", {"company": crm["acme"].pk}, "Invoice", details={"direction": "out"}, occurred_at=ago(1))
    company = staff.get(f"/api/v1/companies/{crm['acme'].pk}/").data["last_contacted_at"]
    assert datetime.fromisoformat(company).astimezone(dt_timezone.utc) == newer.occurred_at.astimezone(dt_timezone.utc)
    # Pipeline cards and the contact list carry it too.
    cards = [c for col in staff.get("/api/v1/contacts/pipeline/").data["columns"] for c in col["cards"]]
    assert next(c for c in cards if c["id"] == crm["ali"].pk)["last_contacted_at"] is not None
    assert next(c for c in staff.get("/api/v1/contacts/").data["results"] if c["id"] == crm["ali"].pk)["last_contacted_at"]


# ================================================================ CSV export


def test_log_export_follows_contacts_export_permission(client_for, people, crm, entries):
    url = f"{LOG}export/"
    org = OrganizationSettings.get_solo()
    org.staff_can_export_contacts = False
    org.save()
    assert client_for(people["staff"]).get(url).status_code == 403
    org.staff_can_export_contacts = True
    org.save()
    res = client_for(people["staff"]).get(url, {"type": "call,email"})
    assert res.status_code == 200 and res["Content-Type"].startswith("text/csv")
    text = res.content.decode("utf-8")
    assert text.startswith("﻿")  # Excel opens Urdu correctly
    lines = text.strip().splitlines()
    assert lines[0].lstrip("﻿").startswith("Date,Type,Direction,Contact,Company,Vendor,Subject,Summary")
    assert len(lines) == 3 and "Discussed order" in text and "Prefers mornings" not in text and "Site visit" not in text
    assert AuditLog.objects.filter(action="export", object_repr="communication log (2)").exists()


def test_log_export_is_formula_safe_and_scoped(client_for, people, crm):
    log(client_for(people["outsider"]), "note", {"contact": crm["ops"].pk}, "=HYPERLINK(\"http://evil\")")
    manager_csv = client_for(people["manager"]).get(f"{LOG}export/").content.decode("utf-8")
    assert "HYPERLINK" not in manager_csv  # another department's record
    admin_csv = client_for(people["admin"]).get(f"{LOG}export/").content.decode("utf-8")
    assert "'=HYPERLINK" in admin_csv


# ================================================================ dashboard: my follow-ups due


def test_my_follow_ups_due_widget(client_for, people, crm):
    staff, colleague = client_for(people["staff"]), client_for(people["colleague"])
    today = office_today()
    mine = log(staff, "call", {"contact": crm["ali"].pk}, "Mine", details={"direction": "out", "outcome": "connected"},
               follow_up_on=str(today - timedelta(days=1)))
    handed = log(staff, "note", {"contact": crm["ali"].pk}, "Handed over", follow_up_on=str(today),
                 follow_up_assignee=people["colleague"].pk)
    no_task = log(staff, "note", {"company": crm["acme"].pk}, "No task", follow_up_on=str(today + timedelta(days=2)), follow_up_skip=True)
    log(staff, "note", {"contact": crm["ali"].pk}, "Far away", follow_up_on=str(today + timedelta(days=20)))
    done = log(staff, "note", {"contact": crm["ali"].pk}, "Done one", follow_up_on=str(today))
    staff.patch(f"/api/v1/tasks/{Task.objects.get(follow_up_of=done).pk}/", {"status": "done"}, format="json")

    items = staff.get("/api/v1/dashboard/").data["follow_ups_due"]
    assert [i["id"] for i in items] == [mine.pk, no_task.pk]
    assert items[0]["is_overdue"] is True and items[0]["title"] == "Ali Khan" and items[0]["task_id"]
    assert items[1]["url"] == f"/companies/{crm['acme'].pk}" and items[1]["task_id"] is None
    assert [i["id"] for i in colleague.get("/api/v1/dashboard/").data["follow_ups_due"]] == [handed.pk]
