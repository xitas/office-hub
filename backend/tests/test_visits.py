"""Field visits: who plans for whom, approvals (Organization setting), who sees what, changes and their
notifications, closing and cancelling, reminders with Urdu time words, the connections (timeline of the contact,
company or vendor; calendar; pending approvals; attendance; tasks), query counts and seed."""
import io
from datetime import datetime, time, timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.contacts.models import Company, Contact
from apps.core.models import AuditLog, OrganizationSettings
from apps.core.office_time import office_today, office_tz
from apps.dashboard import approvals
from apps.notifications.models import Notification
from apps.tasks.models import Task
from apps.vendors.models import Vendor
from apps.visits import services
from apps.visits.models import Visit

pytestmark = pytest.mark.django_db

URL = "/api/v1/visits/"


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {
        "admin": admin, "manager": manager, "staff": staff,
        "colleague": make_user("colleague@test.com", full_name="Sara Colleague", language="ur"),
        "ops": make_user("ops.person@test.com", department="ops", full_name="Omar Ops"),
        "ops_manager": make_user("ops.manager@test.com", role="manager", department="ops", full_name="Olga Manager"),
    }


@pytest.fixture
def client_rec(people):
    company = Company.objects.create(name="Clifton Retail", city="Lahore", address="Main Boulevard", assigned_to=people["staff"])
    contact = Contact.objects.create(first_name="Ali", last_name="Khan", company=company, assigned_to=people["staff"], city="Lahore")
    return {"company": company, "contact": contact}


def at(days, hh, mm=0):
    return datetime.combine(office_today() + timedelta(days=days), time(hh, mm), tzinfo=office_tz())


def plan(client, **data):
    body = {"title": "Quarterly review", "purpose": "meeting", "start": at(1, 11).isoformat(), "end": at(1, 12).isoformat(), **data}
    return client.post(URL, body, format="json")


# ================================================================ planning, approvals and seeing


def test_planning_per_role_and_approval(client_for, people, client_rec, django_capture_on_commit_callbacks):
    staff, colleague, manager, ops_manager, admin = (client_for(people[k]) for k in ("staff", "colleague", "manager", "ops_manager", "admin"))
    company = client_rec["company"]
    assert plan(staff, company=company.pk, assigned_to=people["colleague"].pk).status_code == 400  # staff plan their own
    assert plan(manager, company=company.pk, assigned_to=people["ops"].pk).status_code == 400  # not their department
    assert plan(staff, company=company.pk, end=at(1, 10).isoformat()).status_code == 400
    assert plan(staff, company=company.pk, contact=client_rec["contact"].pk).status_code == 400  # one record
    assert plan(staff).status_code == 400  # who or where
    assert plan(staff, place_name="Site", latitude="31.5").status_code == 400  # both coordinates
    assert plan(staff, company=company.pk, companions=[people["ops"].pk]).status_code == 400  # companions: same department
    # A staff member's own visit waits for their manager (setting on by default).
    with django_capture_on_commit_callbacks(execute=True):
        res = plan(staff, company=company.pk, companions=[people["colleague"].pk], latitude="31.520400", longitude="74.358700")
    assert res.status_code == 201 and res.data["status"] == "pending" and res.data["place"] == "Clifton Retail"
    pk = res.data["id"]
    ask = Notification.objects.get(type="approval_request")
    assert ask.recipient == people["manager"] and ask.title == "Staff plans a field visit"
    told = Notification.objects.get(type="visit", recipient=people["colleague"])  # a companion hears of it, in Urdu
    assert told.title == "فیلڈ وزٹ: Quarterly review"
    assert ops_manager.post(f"{URL}{pk}/decide/", {"approve": True}, format="json").status_code == 404  # can't see it
    assert staff.post(f"{URL}{pk}/decide/", {"approve": True}, format="json").status_code == 403
    with django_capture_on_commit_callbacks(execute=True):
        assert manager.post(f"{URL}{pk}/decide/", {"approve": True}, format="json").data["status"] == "planned"
    assert Notification.objects.filter(type="approval_result", recipient=people["staff"], title="Visit approved: Quarterly review").exists()
    # Managers plan for their people (planned at once, the person is told); with the setting off, staff plan directly.
    with django_capture_on_commit_callbacks(execute=True):
        res = plan(manager, contact=client_rec["contact"].pk, assigned_to=people["staff"].pk, title="Collect cheque", purpose="collection")
    assert res.data["status"] == "planned"
    assert Notification.objects.filter(type="visit", recipient=people["staff"], title="Field visit: Collect cheque").exists()
    OrganizationSettings.objects.update(visits_need_approval=False)
    OrganizationSettings.get_solo().save()  # refresh the cached settings
    assert plan(staff, place_name="Hall Road market", title="Buy cables").data["status"] == "planned"
    # Who sees what.
    titles = lambda c, **p: sorted(v["title"] for v in c.get(URL, p).data)  # noqa: E731
    assert titles(staff) == ["Buy cables", "Collect cheque", "Quarterly review"]
    assert titles(colleague) == ["Quarterly review"]  # as a companion
    assert titles(client_for(people["ops"])) == []
    team = {"scope": "team", "from": office_today().isoformat(), "to": (office_today() + timedelta(days=2)).isoformat()}
    assert len(manager.get(URL, team).data) == 3 and ops_manager.get(URL, team).data == [] and len(admin.get(URL, team).data) == 3
    assert staff.get(URL, team).status_code == 403
    assert AuditLog.objects.filter(object_id=str(pk), changes__status=["pending", "planned"]).exists()


def test_changes_close_cancel_and_notifications(client_for, people, client_rec, django_capture_on_commit_callbacks):
    staff, colleague, manager = (client_for(people[k]) for k in ("staff", "colleague", "manager"))
    with django_capture_on_commit_callbacks(execute=True):
        pk = plan(manager, company=client_rec["company"].pk, assigned_to=people["staff"].pk, companions=[people["colleague"].pk]).data["id"]
    Notification.objects.all().delete()
    with django_capture_on_commit_callbacks(execute=True):
        res = staff.patch(f"{URL}{pk}/", {"start": at(1, 14).isoformat(), "end": at(1, 15).isoformat()}, format="json")
    assert res.status_code == 200
    changed = Notification.objects.get(title="وزٹ میں تبدیلی: Quarterly review")  # the companion, in Urdu with Urdu time words
    assert changed.recipient == people["colleague"] and "دوپہر 2:00–دوپہر 3:00" in changed.body
    assert not Notification.objects.filter(recipient=people["staff"]).exists()  # not the person who changed it
    entry = AuditLog.objects.filter(object_id=str(pk), action="update").latest("id")
    assert set(entry.changes) == {"start", "end"}
    with django_capture_on_commit_callbacks(execute=True):
        staff.patch(f"{URL}{pk}/", {"companions": []}, format="json")
    assert Notification.objects.filter(recipient=people["colleague"], message_key="visit_cancelled").exists()
    assert colleague.get(f"{URL}{pk}/").status_code == 404  # no longer going
    assert staff.post(f"{URL}{pk}/close/", {}, format="json").status_code == 400  # not started yet
    Visit.objects.filter(pk=pk).update(start=at(0, 0, 1), end=at(0, 0, 30))
    with django_capture_on_commit_callbacks(execute=True):
        res = staff.post(f"{URL}{pk}/close/", {"note": "Order confirmed"}, format="json")
    assert res.data["status"] == "done" and res.data["closed_by_name"] == "Staff"
    done = Notification.objects.get(message_key="visit_done")  # whoever planned it for someone else
    assert done.recipient == people["manager"] and "Order confirmed" in done.body
    assert staff.patch(f"{URL}{pk}/", {"title": "x"}, format="json").status_code == 403  # closed
    other = plan(manager, company=client_rec["company"].pk, assigned_to=people["staff"].pk).data["id"]
    with django_capture_on_commit_callbacks(execute=True):
        assert staff.post(f"{URL}{other}/cancel/", {"note": "Client away"}, format="json").data["status"] == "cancelled"
    assert Notification.objects.filter(recipient=people["manager"], message_key="visit_cancelled").exists()


def test_reminders_once_with_urdu_time_words(people, client_rec, django_capture_on_commit_callbacks):
    now = timezone.now()
    visit = Visit.objects.create(title="Demo", company=client_rec["company"], assigned_to=people["colleague"], status="planned",
                                 start=now + timedelta(minutes=20), end=now + timedelta(minutes=80))
    Visit.objects.create(title="Waiting", place_name="Site", assigned_to=people["staff"], status="pending",
                         start=now + timedelta(minutes=10), end=now + timedelta(minutes=40))
    Visit.objects.create(title="Later", place_name="Site", assigned_to=people["staff"], status="planned",
                         start=now + timedelta(hours=2), end=now + timedelta(hours=3))
    with django_capture_on_commit_callbacks(execute=True):
        assert services.send_reminders(now) == 1  # not the pending one, not the later one
    assert services.send_reminders(now) == 0  # once per start time
    note = Notification.objects.get(message_key="visit_reminder")
    assert note.recipient == people["colleague"] and note.title == "30 منٹ میں وزٹ: Demo"
    assert any(word in note.body for word in ("صبح", "دوپہر", "شام", "رات"))
    Visit.objects.filter(pk=visit.pk).update(start=now + timedelta(minutes=25))  # moved: reminded again
    assert services.send_reminders(now) == 1


# ================================================================ connections


def test_timeline_calendar_approvals_attendance_and_tasks(client_for, people, client_rec):
    staff, manager = client_for(people["staff"]), client_for(people["manager"])
    vendor = Vendor.objects.create(name="Bismillah Auto Workshop", phone="0302 1")
    task = Task.objects.create(title="Follow up with Clifton Retail", company=client_rec["company"], created_by=people["staff"])
    task.assignees.set([people["staff"]])
    today = Visit.objects.create(title="Morning call-in", company=client_rec["company"], assigned_to=people["staff"], status="planned",
                                 start=at(0, 23, 0), end=at(0, 23, 30), task=task, created_by=people["staff"])
    Visit.objects.create(title="Service the car", vendor=vendor, assigned_to=people["staff"], status="done",
                         start=at(-2, 10), end=at(-2, 11), closed_at=timezone.now() - timedelta(days=2))
    Visit.objects.create(title="Pending visit", place_name="Site", assigned_to=people["staff"], status="pending", start=at(2, 10), end=at(2, 11))
    timeline = staff.get("/api/v1/timeline/", {"company": client_rec["company"].pk}).data["results"]
    assert [(e["kind"], e["summary"]) for e in timeline if e["kind"] == "visit"] == [("visit", "Morning call-in")]
    vendor_line = staff.get("/api/v1/timeline/", {"vendor": vendor.pk}).data["results"]
    assert [e["details"]["status"] for e in vendor_line if e["kind"] == "visit"] == ["done"]
    feed = staff.get("/api/v1/calendar/", {"from": office_today().isoformat(), "to": (office_today() + timedelta(days=3)).isoformat()}).data["items"]
    assert [i["title"] for i in feed if i["type"] == "visit"] == ["Morning call-in", "Pending visit"]
    assert [i["title"] for i in manager.get("/api/v1/dashboard/").data["pending_approvals"]] == ["Staff"]
    assert staff.get("/api/v1/attendance/today/").data["visits_today"] == 1
    assert [v["title"] for v in staff.get(URL, {"task": task.pk}).data] == ["Morning call-in"]
    assert [v["title"] for v in staff.get(URL, {"scope": "today"}).data] == ["Morning call-in"]
    assert [v["title"] for v in manager.get(URL, {"scope": "today"}).data] == ["Morning call-in"]  # the team's
    assert today.task_id == task.pk


def test_approvals_widget_stays_one_query(people, client_rec):
    Visit.objects.create(title="Pending visit", place_name="Site", assigned_to=people["staff"], status="pending", start=at(2, 10), end=at(2, 11))
    with CaptureQueriesContext(connection) as ctx:
        items = approvals.pending(people["manager"])
    assert len(ctx) == 1 and [i["badge"] for i in items] == ["Visit"]


def test_visit_lists_do_not_grow(client_for, people, client_rec, make_user):
    manager = client_for(people["manager"])
    vendor = Vendor.objects.create(name="V", phone="0300 1")

    def counts():
        out = []
        span = {"from": office_today().isoformat(), "to": (office_today() + timedelta(days=3)).isoformat()}
        for url, params in ((URL, {}), (URL, {"scope": "team", **span}), (URL, {"scope": "today"}), (URL, {"scope": "approvals"}),
                            (URL, {"company": client_rec["company"].pk}), ("/api/v1/calendar/", span),
                            ("/api/v1/timeline/", {"company": client_rec["company"].pk}), ("/api/v1/timeline/", {"vendor": vendor.pk}),
                            ("/api/v1/attendance/today/", {}), (f"{URL}people/", {})):
            with CaptureQueriesContext(connection) as ctx:
                assert manager.get(url, params).status_code == 200, url
            out.append(len(ctx))
        return out

    def add(i):
        person = make_user(f"p{i}@test.com")
        for status, day in (("planned", 0), ("pending", 1), ("done", 2)):
            v = Visit.objects.create(title=f"V{i}{status}", company=client_rec["company"], assigned_to=person, status=status,
                                     start=at(day, 22, 0), end=at(day, 23, 0), created_by=people["manager"])
            v.companions.set([people["manager"]])
        Visit.objects.create(title=f"Vendor {i}", vendor=vendor, assigned_to=person, status="done", start=at(0, 21), end=at(0, 22))

    add(0)
    small = counts()
    for i in range(1, 8):
        add(i)
    assert counts() == small


def test_seed_creates_visits(db):
    from django.core.management import call_command

    call_command("seed_demo", stdout=io.StringIO())
    statuses = set(Visit.objects.values_list("status", flat=True))
    assert statuses >= {"planned", "pending", "done"}
    assert Visit.objects.filter(latitude__isnull=False).exists() and Visit.objects.filter(vendor__isnull=False).exists()
    assert Visit.objects.filter(task__isnull=False).exists()
    assert not Notification.objects.filter(type="visit").exists()


def test_record_link_only_when_the_viewer_can_open_it(client_for, people, make_user):
    """Someone going on a colleague's client visit sees the client's name, but no link to a record they can't open."""
    theirs = Company.objects.create(name="Manager's client", assigned_to=people["manager"])
    visit = Visit.objects.create(title="Joint visit", company=theirs, assigned_to=people["manager"], status="planned",
                                 start=at(1, 10), end=at(1, 11))
    visit.companions.set([people["staff"]])
    seen = client_for(people["staff"]).get(f"{URL}{visit.pk}/").data
    assert seen["company"]["name"] == "Manager's client" and seen["record_visible"] is False
    assert client_for(people["manager"]).get(f"{URL}{visit.pk}/").data["record_visible"] is True
