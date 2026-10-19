"""Phase 5 review: every local-coordination list and view keeps the same number of queries as the data grows.

One dataset touches every slice: vendors with categories and timeline entries, visits (pending, planned, done) with
companions, pins, check-ins, reports with photos and follow-up tasks, errands in each state with updates and proof
photos, and pinned contacts and companies. Each endpoint is measured for an admin, a manager and a staff member with
one person's worth of data, then again after six more people's worth; the counts must not change.
"""
import io
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from PIL import Image

from apps.accounts.models import User
from apps.contacts.models import Company, Contact
from apps.core.office_time import office_today
from apps.errands import services as errands
from apps.errands.models import Errand
from apps.timeline.models import TimelineEntry
from apps.vendors.models import Vendor, VendorCategory
from apps.visits import reports
from apps.visits.models import Visit, VisitCheck

pytestmark = pytest.mark.django_db
PIN = (Decimal("31.520400"), Decimal("74.358700"))


def _jpg(name="p.jpg"):
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(buf, "JPEG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")


@pytest.fixture
def world(make_user, departments):
    roles = {
        "admin": make_user("a@t.com", User.Role.ADMIN, department=None),
        "manager": make_user("m@t.com", User.Role.MANAGER),
        "staff": make_user("s@t.com"),
    }
    category = VendorCategory.objects.create(name="Courier", name_ur="کوریئر")
    vendor = Vendor.objects.create(name="TCS", phone="042 111 123 456", latitude=PIN[0], longitude=PIN[1], created_by=roles["admin"])
    vendor.categories.set([category])
    company = Company.objects.create(name="Saba", assigned_to=roles["staff"], latitude=PIN[0], longitude=PIN[1])
    now = timezone.now()
    visit = Visit.objects.create(title="Fixed", company=company, assigned_to=roles["staff"], status="planned", start=now - timedelta(minutes=30),
                                 end=now + timedelta(minutes=30), created_by=roles["manager"])
    errand = Errand.objects.create(title="Fixed", kind="courier", vendor=vendor, requested_by=roles["staff"], department=roles["staff"].department,
                                   assigned_to=roles["staff"], status="assigned", due_at=now)
    return {"roles": roles, "vendor": vendor, "category": category, "company": company, "visit": visit, "errand": errand, "make_user": make_user}


def grow(world, i):
    """One more person's worth of everything, much of it around the fixed vendor, company, visit and errand."""
    roles, now = world["roles"], timezone.now()
    person = world["make_user"](f"p{i}@t.com", department="sales")
    other = world["make_user"](f"o{i}@t.com", department="ops")
    vendor = Vendor.objects.create(name=f"V{i}", phone=f"0300 12345{i:02d}", latitude=PIN[0], longitude=PIN[1], created_by=person)
    vendor.categories.set([world["category"]])
    Contact.objects.create(first_name=f"C{i}", assigned_to=roles["staff"], company=world["company"], latitude=PIN[0], longitude=PIN[1])
    Company.objects.create(name=f"Co{i}", assigned_to=person, latitude=PIN[0], longitude=PIN[1])
    TimelineEntry.objects.create(kind="call", vendor=world["vendor"], summary=f"Call {i}", details={"direction": "out", "outcome": "connected"}, created_by=person)
    world["visit"].companions.add(person)
    VisitCheck.objects.create(visit=world["visit"], user=person, checked_in_at=now, in_location="recorded", in_latitude=PIN[0], in_longitude=PIN[1])
    for status, who in (("planned", roles["staff"]), ("pending", person), ("done", other)):
        v = Visit.objects.create(title=f"{status} {i}", company=world["company"] if who != other else None, place_name="Site", assigned_to=who,
                                 status=status, start=now - timedelta(minutes=20), end=now + timedelta(minutes=40), created_by=roles["manager"],
                                 latitude=PIN[0], longitude=PIN[1])
        v.companions.add(roles["staff"]) if who == other else None
    done = Visit.objects.create(title=f"Reported {i}", company=world["company"], assigned_to=person, status="planned",
                                start=now - timedelta(minutes=20), end=now + timedelta(minutes=40), created_by=roles["manager"])
    done.companions.add(roles["staff"])
    VisitCheck.objects.create(visit=done, user=person, checked_in_at=now, in_location="declined", checked_out_at=now, out_location="declined")
    reports.save(person, Visit.objects.get(pk=done.pk), {"outcome": "follow_up", "notes": "n", "next_action": "call", "next_action_on": office_today()},
                 photos=[_jpg()], announce=False)
    for status in ("open", "assigned", "on_the_way", "done"):
        e = Errand.objects.create(title=f"E {status} {i}", kind="pickup", vendor=world["vendor"], requested_by=roles["staff"],
                                  department=roles["staff"].department, assigned_to=None if status == "open" else person, status=status,
                                  due_at=now, latitude=PIN[0], longitude=PIN[1])
        errands._step(e, "open", roles["staff"])
        if status == "done":
            from apps.core import photos
            from apps.errands.models import ErrandPhoto

            upload = _jpg()
            photos.save_photos(lambda name, size, info: ErrandPhoto(errand=e, original_name=name, size=size, **info), person,
                               [(upload, photos.clean_photo(upload))])
    errands._step(world["errand"], "on_the_way", roles["staff"], f"step {i}")


def endpoints(world, role):
    today = office_today()
    week = {"from": today.isoformat(), "to": (today + timedelta(days=6)).isoformat()}
    vendor, company, visit, errand = world["vendor"], world["company"], world["visit"], world["errand"]
    out = {
        "vendors": ("/api/v1/vendors/", {}),
        "vendor": (f"/api/v1/vendors/{vendor.pk}/", {}),
        "vendor activity": (f"/api/v1/vendors/{vendor.pk}/activity/", {}),
        "vendor categories": ("/api/v1/vendors/categories/", {}),
        "vendor timeline": ("/api/v1/timeline/", {"vendor": vendor.pk}),
        "company timeline": ("/api/v1/timeline/", {"company": company.pk}),
        "visit log": ("/api/v1/timeline/log/", {"type": "visit"}),
        "my visits": ("/api/v1/visits/", {}),
        "past visits": ("/api/v1/visits/", {"when": "past"}),
        "today's visits": ("/api/v1/visits/", {"scope": "today"}),
        "company's visits": ("/api/v1/visits/", {"company": company.pk}),
        "visit": (f"/api/v1/visits/{visit.pk}/", {}),
        "visit people": ("/api/v1/visits/people/", {}),
        "my errands": ("/api/v1/errands/", {}),
        "errands I asked for": ("/api/v1/errands/", {"scope": "requested"}),
        "waiting errands": ("/api/v1/errands/", {"scope": "open"}),
        "finished errands": ("/api/v1/errands/", {"scope": "done"}),
        "today's errands": ("/api/v1/errands/", {"scope": "today"}),
        "vendor's errands": ("/api/v1/errands/", {"vendor": vendor.pk}),
        "map config": ("/api/v1/map/config/", {}),
        "calendar": ("/api/v1/calendar/", week),
        "attendance today": ("/api/v1/attendance/today/", {}),
        "dashboard": ("/api/v1/dashboard/", {}),
        "search": ("/api/v1/search/", {"q": "V1"}),
    }
    if role != "staff":
        out |= {
            "team visits": ("/api/v1/visits/", {"scope": "team", **week}),
            "visit approvals": ("/api/v1/visits/", {"scope": "approvals"}),
            "team errands": ("/api/v1/errands/", {"scope": "team"}),
            "map today": ("/api/v1/map/", {}),
            "map week": ("/api/v1/map/", week),
        }
    out["errand"] = (f"/api/v1/errands/{errand.pk}/", {})
    return out


def measure(client, urls):
    counts = {}
    for name, (url, params) in urls.items():
        client.get(url, params)  # warm the settings cache
        with CaptureQueriesContext(connection) as ctx:
            res = client.get(url, params)
        assert res.status_code == 200, (name, res.status_code, getattr(res, "data", None))
        counts[name] = len(ctx)
    return counts


@pytest.mark.parametrize("role", ["admin", "manager", "staff"])
def test_phase5_endpoints_do_not_grow(role, world, client_for):
    client = client_for(world["roles"][role])
    urls = endpoints(world, role)
    grow(world, 0)
    small = measure(client, urls)
    for i in range(1, 7):
        grow(world, i)
    grown = measure(client, urls)
    assert {k: (small[k], grown[k]) for k in small if small[k] != grown[k]} == {}
    assert grown["dashboard"] <= 22
