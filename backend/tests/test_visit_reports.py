"""Visit reports: who writes them and when, the visit marked done, the report on the client's timeline (one entry,
the communication log, "last contacted"), the next action as a follow-up task (kept in step, done with the task),
the lead status moved from the report, photos (task-file rules, location metadata stripped, private downloads),
visits to a vendor and to a place, notifications in Urdu, the audit log and query counts."""
import io
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from PIL import Image

from apps.contacts.models import Contact, ContactStatusChange
from apps.core.models import AuditLog
from apps.core.office_time import office_today
from apps.notifications.models import Notification
from apps.tasks.models import Task
from apps.timeline.models import TimelineEntry
from apps.vendors.models import Vendor
from apps.visits.models import Visit, VisitCheck, VisitPhoto, VisitReport

pytestmark = pytest.mark.django_db

URL = "/api/v1/visits/"


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {
        "admin": admin, "manager": manager, "staff": staff,
        "colleague": make_user("colleague@test.com", full_name="Sara Colleague"),
        "ops_manager": make_user("ops.manager@test.com", role="manager", department="ops", full_name="Olga Manager", language="ur"),
        "ops": make_user("ops.person@test.com", department="ops", full_name="Omar Ops"),
    }


def _visit(people, who="staff", planner="manager", minutes=-30, **kw):
    now = timezone.now()
    v = Visit.objects.create(title=kw.pop("title", "Quarterly review"), assigned_to=people[who], status="planned", created_by=people[planner],
                             start=now + timedelta(minutes=minutes), end=now + timedelta(minutes=minutes + 60), **kw)
    return v


@pytest.fixture
def lead(people):
    return Contact.objects.create(first_name="Hira", last_name="Rana", status="contacted", assigned_to=people["staff"])


def photo(name="site.jpg", fmt="JPEG", gps=True, size=(1200, 900)):
    """A photo straight from a phone: EXIF with a GPS position and the camera model."""
    img = Image.new("RGB", size, (30, 120, 200))
    exif = Image.Exif()
    exif[0x0110] = "Pixel 9"  # camera model
    if gps:
        exif[0x8825] = {1: "N", 2: (31.0, 31.0, 13.0), 3: "E", 4: (74.0, 21.0, 32.0)}
    out = io.BytesIO()
    img.save(out, fmt, exif=exif.tobytes()) if fmt in ("JPEG", "WEBP", "PNG") else img.save(out, fmt)
    return SimpleUploadedFile(name, out.getvalue(), content_type=f"image/{fmt.lower()}")


def test_report_marks_done_goes_on_the_timeline_and_makes_the_follow_up(client_for, people, lead, django_capture_on_commit_callbacks):
    v = _visit(people, contact=lead)
    VisitCheck.objects.create(visit=v, user=people["staff"], checked_in_at=v.start + timedelta(minutes=2), in_location="declined",
                              checked_out_at=v.start + timedelta(minutes=50), out_location="declined")
    staff = client_for(people["staff"])
    day = office_today() + timedelta(days=3)
    with django_capture_on_commit_callbacks(execute=True):
        res = staff.post(f"{URL}{v.pk}/report/", {
            "outcome": "follow_up", "notes": "They want a quote for 40 seats.\nCall back after Eid.", "next_action": "Send the quote",
            "next_action_on": day.isoformat(), "contact_status": "in_discussion", "status_reason": "Asked for a quote",
        }, format="json")
    assert res.status_code == 200, res.data
    assert res.data["status"] == "done" and res.data["report"]["outcome"] == "follow_up" and not res.data["can_close"]
    report = VisitReport.objects.get(visit=v)
    # One timeline entry: the report, in place of the automatic "visit" entry.
    items = client_for(people["staff"]).get("/api/v1/timeline/", {"contact": lead.pk, "type": "visit"}).data["results"]
    assert len(items) == 1 and items[0]["id"] == f"entry:{report.entry_id}" and not items[0]["editable"]
    assert items[0]["details"]["outcome"] == "follow_up" and items[0]["details"]["on_site"][1] is not None
    assert report.entry.occurred_at == v.start + timedelta(minutes=50)  # when they left
    # The follow-up task: assigned to the writer, due on the day, linked to the contact and the entry.
    task = Task.objects.get(follow_up_of=report.entry)
    assert task.title == "Follow up with Hira Rana: Send the quote" and task.due_date == day and task.contact == lead
    assert list(task.assignees.all()) == [people["staff"]] and report.follow_up_task == task
    # The lead moved on the pipeline, with its history.
    lead.refresh_from_db()
    assert lead.status == "in_discussion"
    assert ContactStatusChange.objects.filter(contact=lead, from_status="contacted", to_status="in_discussion", reason="Asked for a quote").exists()
    # The communication log lists it, and it counts as being in touch.
    log = client_for(people["manager"]).get("/api/v1/timeline/log/", {"type": "visit"}).data["results"]
    assert [e["entry_id"] for e in log] == [report.entry_id]
    detail = client_for(people["staff"]).get(f"/api/v1/contacts/{lead.pk}/").data
    assert detail.get("last_contacted_at") is not None
    # Whoever planned it hears; the writer doesn't. Audited.
    note = Notification.objects.get(message_key="visit_reported")
    assert note.recipient == people["manager"] and note.title == "Visit report: Quarterly review"
    assert "Outcome: Needs follow-up." in note.body and f"Next: Send the quote by {day:%d/%m/%Y}." in note.body
    assert not Notification.objects.filter(message_key="visit_done").exists()
    assert AuditLog.objects.filter(object_id=str(v.pk), description="Visit report written").exists()
    # Changing the date moves the task; finishing the task marks the follow-up done.
    later = day + timedelta(days=2)
    res = staff.post(f"{URL}{v.pk}/report/", {"outcome": "follow_up", "notes": "Quote ready.", "next_action": "Send the quote",
                                              "next_action_on": later.isoformat()}, format="json")
    assert res.status_code == 200
    task.refresh_from_db()
    assert task.due_date == later and Task.objects.filter(follow_up_of=report.entry).count() == 1
    assert AuditLog.objects.filter(object_id=str(v.pk), description="Visit report changed").exists()
    task.status = Task.Status.DONE
    task.completed_at = timezone.now()
    task.save()
    report.entry.refresh_from_db()
    assert report.entry.follow_up_done_at is not None and report.entry.summary == "Quote ready."


def test_who_writes_and_when(client_for, people, lead):
    v = _visit(people, contact=lead)
    v.companions.set([people["colleague"]])
    body = {"outcome": "good"}
    assert client_for(people["ops_manager"]).post(f"{URL}{v.pk}/report/", body, format="json").status_code == 404  # can't see it
    later = _visit(people, minutes=180)
    assert client_for(people["staff"]).post(f"{URL}{later.pk}/report/", body, format="json").status_code == 403  # not started
    planned_by_me = _visit(people, who="colleague", planner="staff")
    assert client_for(people["staff"]).post(f"{URL}{planned_by_me.pk}/report/", body, format="json").status_code == 403  # didn't go
    assert client_for(people["staff"]).get(f"{URL}{planned_by_me.pk}/").data["can_report"] is False
    # A companion who can't see the contact writes the report but can't move the lead.
    res = client_for(people["colleague"]).post(f"{URL}{v.pk}/report/", {"outcome": "good", "contact_status": "won"}, format="json")
    assert res.status_code == 400 and "contact_status" in res.data["errors"]
    assert client_for(people["colleague"]).post(f"{URL}{v.pk}/report/", {"outcome": "good", "next_action_on": office_today().isoformat()},
                                                format="json").status_code == 400  # a date needs an action
    assert client_for(people["colleague"]).post(f"{URL}{v.pk}/report/", body, format="json").status_code == 200
    assert client_for(people["manager"]).post(f"{URL}{v.pk}/report/", {"outcome": "no_result"}, format="json").status_code == 200  # their manager
    cancelled = _visit(people, minutes=-120)
    cancelled.status = "cancelled"
    cancelled.save()
    assert client_for(people["admin"]).post(f"{URL}{cancelled.pk}/report/", body, format="json").status_code == 403


def test_photos_keep_no_location_and_follow_the_file_rules(client_for, people, lead):
    v = _visit(people, contact=lead)
    staff = client_for(people["staff"])
    res = staff.post(f"{URL}{v.pk}/report/", {"outcome": "good", "photos": [photo(), photo("shelf.png", "PNG"), photo("door.webp", "WEBP")]},
                     format="multipart")
    assert res.status_code == 200, res.data
    photos = res.data["report"]["photos"]
    assert len(photos) == 3 and all(p["thumbnail_url"] for p in photos)
    for p in VisitPhoto.objects.all():
        with p.file.open("rb") as f, Image.open(f) as img:
            assert not img.getexif() and "exif" not in img.info  # no GPS, no camera
        assert p.width == 1200 and p.height == 900
    # Downloads: people who can see the visit only.
    first = photos[0]
    for who, url, code in (("manager", "download_url", 200), ("ops_manager", "download_url", 404), ("ops", "thumbnail_url", 404)):
        got = client_for(people[who]).get(f"/api/v1{first[url]}")
        assert got.status_code == code
    # Photos only, real ones, at most 8.
    pdf = SimpleUploadedFile("plan.pdf", b"%PDF-1.4 test", content_type="application/pdf")
    assert staff.post(f"{URL}{v.pk}/report/", {"outcome": "good", "photos": [pdf]}, format="multipart").status_code == 400
    fake = SimpleUploadedFile("fake.jpg", b"<html>not a photo</html>", content_type="image/jpeg")
    assert staff.post(f"{URL}{v.pk}/report/", {"outcome": "good", "photos": [fake]}, format="multipart").status_code == 400
    many = [photo(f"p{i}.jpg", size=(40, 30)) for i in range(6)]
    assert staff.post(f"{URL}{v.pk}/report/", {"outcome": "good", "photos": many}, format="multipart").status_code == 400
    # Removing one deletes its files; the timeline entry's photo count follows. (Not the one downloaded above: on
    # Windows the test client's open download keeps that file in use.)
    gone = VisitPhoto.objects.get(pk=photos[1]["id"])
    path = gone.file.name
    res = staff.post(f"{URL}{v.pk}/report/", {"outcome": "good", "remove_photos": [gone.pk]}, format="multipart")
    assert res.status_code == 200 and len(res.data["report"]["photos"]) == 2, res.data
    assert not gone.file.storage.exists(path)
    assert VisitReport.objects.get(visit=v).entry.details["photos"] == 2


def test_vendor_and_place_visits(client_for, people, django_capture_on_commit_callbacks):
    vendor = Vendor.objects.create(name="Bismillah Workshop")
    v = _visit(people, vendor=vendor, title="Car service")
    day = office_today() + timedelta(days=1)
    res = client_for(people["staff"]).post(f"{URL}{v.pk}/report/", {"outcome": "good", "next_action": "Collect the car",
                                                                    "next_action_on": day.isoformat()}, format="json")
    assert res.status_code == 200
    items = client_for(people["staff"]).get("/api/v1/timeline/", {"vendor": vendor.pk, "type": "visit"}).data["results"]
    assert len(items) == 1 and items[0]["follow_up_task"] is not None
    # A place: no timeline, the task is made directly and can go to a colleague (who's told).
    place = _visit(people, place_name="Bank Alfalah, Gulberg", title="Deposit cheques")
    with django_capture_on_commit_callbacks(execute=True):
        res = client_for(people["staff"]).post(f"{URL}{place.pk}/report/", {
            "outcome": "not_met", "next_action": "Go again with the stamp", "next_action_on": day.isoformat(),
            "follow_up_assignee": people["colleague"].pk}, format="json")
    assert res.status_code == 200 and res.data["report"]["on_timeline"] is False
    task = Task.objects.get(pk=res.data["report"]["follow_up_task"]["id"])
    assert task.title == "Next step after Deposit cheques: Go again with the stamp" and list(task.assignees.all()) == [people["colleague"]]
    assert Notification.objects.filter(recipient=people["colleague"], type="task_assigned").exists()
    assert TimelineEntry.objects.filter(kind="visit").count() == 1
    # Someone outside the department can't be given the task.
    other = _visit(people, place_name="Site", title="Other")
    res = client_for(people["staff"]).post(f"{URL}{other.pk}/report/", {
        "outcome": "good", "next_action": "x", "next_action_on": day.isoformat(), "follow_up_assignee": people["ops"].pk}, format="json")
    assert res.status_code == 400 and Visit.objects.get(pk=other.pk).status == "planned"  # nothing saved


def test_report_notification_in_urdu(people, client_for, django_capture_on_commit_callbacks):
    v = _visit(people, who="ops", planner="ops_manager", place_name="Gulberg store", title="Stock count")
    day = office_today() + timedelta(days=2)
    with django_capture_on_commit_callbacks(execute=True):
        res = client_for(people["ops"]).post(f"{URL}{v.pk}/report/", {"outcome": "good", "next_action": "Order shelves",
                                                                      "next_action_on": day.isoformat()}, format="json")
    assert res.status_code == 200
    note = Notification.objects.get(message_key="visit_reported")
    assert note.recipient == people["ops_manager"] and note.title == "وزٹ رپورٹ: Stock count"
    assert "اچھا رہا" in note.body and f"{day:%d/%m/%Y}" in note.body
    assert any(w in note.body for w in ("صبح", "دوپہر", "شام", "رات"))


def test_lists_and_timelines_with_reports_do_not_grow(client_for, people, make_user):
    manager = client_for(people["manager"])
    contact = Contact.objects.create(first_name="Busy", assigned_to=people["staff"])
    params = {"scope": "team", "from": office_today().isoformat(), "to": office_today().isoformat()}

    def count(url, query):
        manager.get(url, query)  # warm the settings cache
        with CaptureQueriesContext(connection) as ctx:
            res = manager.get(url, query)
        assert res.status_code == 200
        return len(ctx)

    def add(i):
        person = make_user(f"p{i}@test.com")
        v = _visit({"p": person, "manager": people["manager"]}, who="p", planner="manager", minutes=-5, contact=contact, title=f"V{i}")
        from apps.visits import reports

        reports.save(person, Visit.objects.get(pk=v.pk), {"outcome": "good", "notes": "ok", "next_action": "call", "next_action_on": office_today()},
                     photos=[photo(f"p{i}.jpg", size=(40, 30))])

    add(0)
    small = (count(URL, params), count("/api/v1/timeline/", {"contact": contact.pk}))
    for i in range(1, 6):
        add(i)
    assert (count(URL, params), count("/api/v1/timeline/", {"contact": contact.pk})) == small


def test_seed_creates_reports(db):
    from django.core.management import call_command

    call_command("seed_demo", stdout=io.StringIO())
    assert VisitReport.objects.filter(entry__isnull=False, follow_up_task__isnull=False).exists()
    assert VisitPhoto.objects.exists()
    assert VisitReport.objects.filter(status_change__isnull=False).exists()
