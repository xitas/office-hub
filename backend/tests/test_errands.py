"""Errands and deliveries: asking, giving out and taking (department rules), on the way, done (reference and proof
photos with location stripped) or not done, cancelling, who sees what (per role, in the API), notifications in
each reader's language (Urdu time words), the "due soon" reminder, the audit log, the timeline and the map, query
counts and the seed."""
import io
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from PIL import Image

from apps.contacts.models import Company
from apps.core.models import AuditLog
from apps.errands import services
from apps.errands.models import Errand, ErrandPhoto
from apps.notifications.models import Notification
from apps.vendors.models import Vendor

pytestmark = pytest.mark.django_db

URL = "/api/v1/errands/"


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {
        "admin": admin, "manager": manager, "staff": staff,
        "colleague": make_user("colleague@test.com", full_name="Sara Colleague", language="ur"),
        "ops": make_user("ops.person@test.com", department="ops", full_name="Omar Ops"),
        "ops_manager": make_user("ops.manager@test.com", role="manager", department="ops", full_name="Olga Manager"),
    }


def photo(name="receipt.jpg"):
    img = Image.new("RGB", (800, 600), (200, 200, 200))
    exif = Image.Exif()
    exif[0x0110] = "Pixel 9"
    exif[0x8825] = {1: "N", 2: (31.0, 31.0, 13.0), 3: "E", 4: (74.0, 21.0, 32.0)}
    out = io.BytesIO()
    img.save(out, "JPEG", exif=exif.tobytes())
    return SimpleUploadedFile(name, out.getvalue(), content_type="image/jpeg")


def test_an_open_errand_is_taken_done_and_everyone_hears(client_for, people, django_capture_on_commit_callbacks):
    staff, colleague = client_for(people["staff"]), client_for(people["colleague"])
    tcs = Vendor.objects.create(name="TCS Express", phone="042 111 123 456")
    due = timezone.now() + timedelta(hours=3)
    with django_capture_on_commit_callbacks(execute=True):
        res = staff.post(URL, {"title": "Courier the contract", "kind": "courier", "vendor": tcs.pk, "due_at": due.isoformat()}, format="json")
    assert res.status_code == 201 and res.data["status"] == "open" and res.data["can_change"]
    pk = res.data["id"]
    assert Notification.objects.get(message_key="errand_open").recipient == people["manager"]  # the department's manager
    # The department sees it waiting; another department doesn't.
    assert [e["id"] for e in colleague.get(URL, {"scope": "open"}).data] == [pk]
    assert client_for(people["ops"]).get(f"{URL}{pk}/").status_code == 404
    assert client_for(people["ops_manager"]).post(f"{URL}{pk}/take/").status_code == 404
    with django_capture_on_commit_callbacks(execute=True):
        res = colleague.post(f"{URL}{pk}/take/")
    assert res.status_code == 200 and res.data["status"] == "assigned" and res.data["assigned_to_name"] == "Sara Colleague"
    assert Notification.objects.get(message_key="errand_taken").recipient == people["staff"]
    assert staff.post(f"{URL}{pk}/start/").status_code == 403  # only the runner (or the managers)
    with django_capture_on_commit_callbacks(execute=True):
        assert colleague.post(f"{URL}{pk}/start/").data["status"] == "on_the_way"
    assert colleague.post(f"{URL}{pk}/finish/", {"done": False}, format="json").status_code == 400  # say why
    with django_capture_on_commit_callbacks(execute=True):
        res = colleague.post(f"{URL}{pk}/finish/", {"done": True, "note": "Booked at the counter.", "reference": "TCS 7781 2290 113",
                                                     "photos": [photo()]}, format="multipart")
    assert res.status_code == 200 and res.data["status"] == "done" and res.data["reference"] == "TCS 7781 2290 113"
    assert [u["status"] for u in res.data["updates"]] == ["open", "assigned", "on_the_way", "done"]
    with ErrandPhoto.objects.get().file.open("rb") as f, Image.open(f) as img:
        assert not img.getexif()  # no GPS, no camera
    done = Notification.objects.get(message_key="errand_done")
    assert done.recipient == people["staff"] and done.title == "Errand done: Courier the contract" and "TCS 7781 2290 113" in done.body
    assert [n.message_key for n in Notification.objects.filter(message_key="errand_started")] == ["errand_started"]
    # Photos: people who can see the errand.
    url = res.data["photos"][0]["thumbnail_url"]
    assert client_for(people["manager"]).get(f"/api/v1{url}").status_code == 200
    assert client_for(people["ops_manager"]).get(f"/api/v1{url}").status_code == 404
    audit = AuditLog.objects.filter(object_id=str(pk))
    assert audit.filter(action="create").exists() and audit.filter(changes__reference=[None, "TCS 7781 2290 113"]).exists()
    # On the vendor's timeline.
    items = staff.get("/api/v1/timeline/", {"vendor": tcs.pk, "type": "errand"}).data["results"]
    assert [i["details"]["errand_id"] for i in items] == [pk]


def test_who_gives_out_changes_and_cancels(client_for, people, django_capture_on_commit_callbacks):
    staff = client_for(people["staff"])
    body = {"title": "Deposit cheques", "kind": "bank", "place_name": "Bank Alfalah, Gulberg"}
    assert staff.post(URL, {**body, "assigned_to": people["ops"].pk}, format="json").status_code == 400  # another department
    assert staff.post(URL, {"title": "Nowhere"}, format="json").status_code == 400  # where?
    assert staff.post(URL, {**body, "latitude": "31.5"}, format="json").status_code == 400  # both or neither
    with django_capture_on_commit_callbacks(execute=True):
        pk = staff.post(URL, {**body, "assigned_to": people["colleague"].pk}, format="json").data["id"]
    note = Notification.objects.get(message_key="errand_assigned")
    assert note.recipient == people["colleague"] and note.title == "آپ کے لیے کام: Deposit cheques"  # in Urdu for Sara
    # The runner can't change or cancel it; the manager gives it to someone else (both are told).
    assert client_for(people["colleague"]).patch(f"{URL}{pk}/", {"title": "x"}, format="json").status_code == 403
    assert client_for(people["colleague"]).post(f"{URL}{pk}/cancel/").status_code == 403
    with django_capture_on_commit_callbacks(execute=True):
        res = client_for(people["manager"]).patch(f"{URL}{pk}/", {"assigned_to": people["staff"].pk}, format="json")
    assert res.status_code == 200 and res.data["assigned_to_name"] == "Staff"
    assert Notification.objects.filter(message_key="errand_reassigned", recipient=people["colleague"]).exists()
    assert Notification.objects.filter(message_key="errand_assigned", recipient=people["staff"]).exists()  # the manager gave it to them
    # Admin sees all; the other department's manager doesn't.
    assert client_for(people["admin"]).get(f"{URL}{pk}/").status_code == 200
    assert client_for(people["ops_manager"]).get(f"{URL}{pk}/").status_code == 404
    assert client_for(people["staff"]).get(URL, {"scope": "team"}).status_code == 403
    with django_capture_on_commit_callbacks(execute=True):
        assert staff.post(f"{URL}{pk}/cancel/", {"note": "Not needed"}, format="json").data["status"] == "cancelled"
    assert staff.post(f"{URL}{pk}/cancel/").status_code == 403  # finished


def test_due_soon_reminder_once_with_urdu_time_words(people):
    errand = Errand.objects.create(title="Collect toner", kind="pickup", place_name="Hall Road", requested_by=people["staff"],
                                   department=people["staff"].department, assigned_to=people["colleague"], status="assigned",
                                   due_at=timezone.now() + timedelta(minutes=40))
    Errand.objects.create(title="Later", kind="pickup", place_name="x", requested_by=people["staff"], department=people["staff"].department,
                          assigned_to=people["colleague"], status="assigned", due_at=timezone.now() + timedelta(hours=3))
    assert services.send_reminders() == 1
    assert services.send_reminders() == 0
    note = Notification.objects.get(message_key="errand_due")
    assert note.recipient == people["colleague"] and note.title == f"کام کا وقت قریب: {errand.title}"
    assert any(w in note.body for w in ("صبح", "دوپہر", "شام", "رات"))


def test_errands_on_the_map_and_company_timeline(client_for, people):
    company = Company.objects.create(name="Ravi Pharma", assigned_to=people["staff"], latitude="31.510600", longitude="74.344600")
    Errand.objects.create(title="Pick up the agreement", kind="pickup", company=company, requested_by=people["manager"],
                          department=people["staff"].department, assigned_to=people["staff"], status="assigned", due_at=timezone.now())
    Errand.objects.create(title="Ops errand", kind="bank", place_name="Bank", requested_by=people["ops_manager"],
                          department=people["ops"].department, status="open", due_at=timezone.now(), latitude="31.5", longitude="74.3")
    data = client_for(people["manager"]).get("/api/v1/map/").data
    assert [(e["title"], e["pin_source"]) for e in data["errands"]] == [("Pick up the agreement", "record")]
    assert len(client_for(people["admin"]).get("/api/v1/map/").data["errands"]) == 2
    items = client_for(people["staff"]).get("/api/v1/timeline/", {"company": company.pk, "type": "errand"}).data["results"]
    assert [i["summary"] for i in items] == ["Pick up the agreement"]


def test_errand_lists_do_not_grow(client_for, people, make_user):
    manager = client_for(people["manager"])

    def count(scope):
        manager.get(URL, {"scope": scope})  # warm the settings cache
        with CaptureQueriesContext(connection) as ctx:
            res = manager.get(URL, {"scope": scope})
        assert res.status_code == 200
        return len(ctx), len(res.data)

    def add(i):
        person = make_user(f"p{i}@test.com")
        tcs = Vendor.objects.create(name=f"V{i}", phone=f"0300 12345{i:02d}")
        e = Errand.objects.create(title=f"E{i}", kind="courier", vendor=tcs, requested_by=person, department=person.department,
                                  assigned_to=person, status="assigned", due_at=timezone.now())
        services._step(e, "open", person)
        services._step(e, "assigned", person)

    add(0)
    small = {s: count(s) for s in ("team", "today")}
    for i in range(1, 7):
        add(i)
    grown = {s: count(s) for s in ("team", "today")}
    assert all(grown[s][0] == small[s][0] and grown[s][1] > small[s][1] for s in grown)


def test_seed_creates_errands(db):
    from django.core.management import call_command

    call_command("seed_demo", stdout=io.StringIO())
    statuses = set(Errand.objects.values_list("status", flat=True))
    assert statuses == {"open", "assigned", "on_the_way", "done", "failed", "cancelled"}
    assert ErrandPhoto.objects.exists() and Errand.objects.filter(vendor__isnull=False, reference__startswith="TCS").exists()
