"""The map: who sees it and which visits, pins (a visit's own, else its record's), check-in locations only for
those allowed (and gone after 90 days), records' pins, pins on contacts/companies/vendors (both or neither,
audited), address search through Nominatim (switched off without a contact email, cached, one a second, mocked
here: never a real call), query counts and the seed."""
import io
import json
from datetime import timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.contacts.models import Company, Contact
from apps.core.models import AuditLog
from apps.core.office_time import office_today
from apps.core.safe_cache import safe_cache
from apps.maps import geocode
from apps.vendors.models import Vendor
from apps.visits.models import Visit, VisitCheck

pytestmark = pytest.mark.django_db

MAP = "/api/v1/map/"
SEARCH = "/api/v1/map/search/"
LAHORE = (Decimal("31.520400"), Decimal("74.358700"))


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {
        "admin": admin, "manager": manager, "staff": staff,
        "ops": make_user("ops.person@test.com", department="ops", full_name="Omar Ops"),
        "ops_manager": make_user("ops.manager@test.com", role="manager", department="ops", full_name="Olga Manager"),
    }


def _visit(person, **kw):
    now = timezone.now()
    return Visit.objects.create(title=kw.pop("title", "Visit"), assigned_to=person, status=kw.pop("status", "planned"),
                                start=now - timedelta(minutes=30), end=now + timedelta(minutes=30), **kw)


def test_map_shows_the_right_visits_pins_and_locations(client_for, people):
    company = Company.objects.create(name="Saba Software", assigned_to=people["staff"], latitude=Decimal("31.469400"), longitude=Decimal("74.272800"))
    own_pin = _visit(people["staff"], title="Own pin", place_name="Site", latitude=LAHORE[0], longitude=LAHORE[1])
    record_pin = _visit(people["staff"], title="Company pin", company=company)
    no_pin = _visit(people["staff"], title="No pin", place_name="Somewhere", status="done")
    _visit(people["staff"], title="Cancelled", place_name="x", status="cancelled")
    ops_visit = _visit(people["ops"], title="Ops visit", place_name="Store")
    own_pin.companions.add(people["ops"])
    VisitCheck.objects.create(visit=own_pin, user=people["staff"], checked_in_at=timezone.now(), in_location="recorded",
                              in_latitude=Decimal("31.521200"), in_longitude=Decimal("74.359000"), in_accuracy=12)
    VisitCheck.objects.create(visit=own_pin, user=people["ops"], checked_in_at=timezone.now(), in_location="recorded",
                              in_latitude=Decimal("31.530000"), in_longitude=Decimal("74.360000"), in_accuracy=8)
    assert client_for(people["staff"]).get(MAP).status_code == 403  # managers and admins
    data = client_for(people["manager"]).get(MAP).data
    by_title = {v["title"]: v for v in data["visits"]}
    assert set(by_title) == {"Own pin", "Company pin", "No pin"}  # their department's; not cancelled
    assert by_title["Own pin"]["pin_source"] == "visit" and by_title["Own pin"]["latitude"] == "31.520400"
    assert by_title["Company pin"]["pin_source"] == "record" and by_title["Company pin"]["longitude"] == "74.272800"
    assert by_title["No pin"]["pin_source"] is None and by_title["No pin"]["latitude"] is None
    checks = {c["user_name"]: c for c in by_title["Own pin"]["checks"]}
    assert checks["Staff"]["in"]["latitude"] == "31.521200"  # their department's manager sees where staff checked in
    assert checks["Omar Ops"]["in"] is None and checks["Omar Ops"]["location_visible"] is False  # not their department
    # Admins see everyone's, and every location; filters by person and status.
    admin = client_for(people["admin"])
    assert {v["title"] for v in admin.get(MAP).data["visits"]} == {"Own pin", "Company pin", "No pin", "Ops visit"}
    assert all(c["in"] for c in next(v for v in admin.get(MAP).data["visits"] if v["title"] == "Own pin")["checks"])
    assert [v["id"] for v in admin.get(MAP, {"person": people["ops"].pk}).data["visits"]] == [ops_visit.pk]
    assert [v["id"] for v in admin.get(MAP, {"status": "done"}).data["visits"]] == [no_pin.pk]
    assert admin.get(MAP, {"from": office_today().isoformat(), "to": (office_today() + timedelta(days=40)).isoformat()}).status_code == 400
    # After 90 days the coordinates are gone, for everyone.
    VisitCheck.objects.update(in_latitude=None, in_longitude=None, in_accuracy=None, location_removed_at=timezone.now())
    gone = next(v for v in admin.get(MAP).data["visits"] if v["title"] == "Own pin")["checks"]
    assert all(c["in"] is None and c["location_removed"] for c in gone)
    assert record_pin.pk in [v["id"] for v in data["visits"]]


def test_records_on_the_map_follow_who_sees_them(client_for, people):
    Contact.objects.create(first_name="Mine", assigned_to=people["staff"], latitude=LAHORE[0], longitude=LAHORE[1])
    Contact.objects.create(first_name="Theirs", assigned_to=people["ops"], latitude=LAHORE[0], longitude=LAHORE[1])
    Contact.objects.create(first_name="Unpinned", assigned_to=people["staff"])
    Vendor.objects.create(name="Workshop", phone="0300 1234567", latitude=LAHORE[0], longitude=LAHORE[1])
    Vendor.objects.create(name="Closed", phone="0300 1234568", is_active=False, latitude=LAHORE[0], longitude=LAHORE[1])
    data = client_for(people["manager"]).get(MAP).data
    assert [c["name"] for c in data["contacts"]] == ["Mine"] and [v["name"] for v in data["vendors"]] == ["Workshop"]
    assert {c["name"] for c in client_for(people["admin"]).get(MAP).data["contacts"]} == {"Mine", "Theirs"}


def test_pins_on_contacts_companies_and_vendors(client_for, people):
    staff = client_for(people["staff"])
    company = Company.objects.create(name="Clifton Retail", assigned_to=people["staff"])
    url = f"/api/v1/companies/{company.pk}/"
    assert staff.patch(url, {"latitude": "31.5"}, format="json").status_code == 400  # both or neither
    assert staff.patch(url, {"latitude": "95", "longitude": "74.3"}, format="json").status_code == 400
    res = staff.patch(url, {"latitude": "31.469400", "longitude": "74.272800"}, format="json")
    assert res.status_code == 200 and res.data["latitude"] == "31.469400"
    entry = AuditLog.objects.filter(object_id=str(company.pk), action="update").latest("id")
    assert "latitude" in entry.changes
    assert staff.patch(url, {"latitude": None, "longitude": None}, format="json").data["latitude"] is None  # cleared
    contact = Contact.objects.create(first_name="Hira", assigned_to=people["staff"])
    assert staff.patch(f"/api/v1/contacts/{contact.pk}/", {"latitude": "31.52", "longitude": "74.35"}, format="json").status_code == 200
    vendor = Vendor.objects.create(name="Workshop", phone="0300 1234567")
    assert staff.patch(f"/api/v1/vendors/{vendor.pk}/", {"latitude": "31.51", "longitude": "74.34"}, format="json").status_code == 200
    assert staff.patch(f"/api/v1/vendors/{vendor.pk}/", {"longitude": None}, format="json").status_code == 400


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _answer(rows):
    return mock.patch("urllib.request.urlopen", return_value=FakeResponse(json.dumps(rows).encode()))


ROWS = [{"display_name": "Liberty Market, Gulberg III, Lahore", "lat": "31.5100", "lon": "74.3440", "type": "marketplace"}]


def test_search_is_off_without_a_contact_email(client_for, people, settings):
    settings.NOMINATIM_CONTACT_EMAIL = ""
    with mock.patch("urllib.request.urlopen") as call:
        res = client_for(people["staff"]).get(SEARCH, {"q": "Liberty Market"})
    assert res.status_code == 503 and res.data["code"] == "search_disabled" and "NOMINATIM_CONTACT_EMAIL" in res.data["detail"]
    call.assert_not_called()
    assert client_for(people["staff"]).get("/api/v1/map/config/").data == {"search_enabled": False, "can_view_map": False}


def test_search_through_nominatim_is_cached_and_one_a_second(client_for, people, settings):
    settings.NOMINATIM_CONTACT_EMAIL = "office@example.com"
    staff = client_for(people["staff"])
    assert staff.get(SEARCH, {"q": "ab"}).status_code == 400
    with _answer(ROWS) as call:
        res = staff.get(SEARCH, {"q": "  Liberty   Market "})
        again = client_for(people["manager"]).get(SEARCH, {"q": "liberty market"})  # someone else, same words: cached
    assert res.status_code == 200 and res.data["results"] == [{"name": ROWS[0]["display_name"], "latitude": 31.51, "longitude": 74.344, "kind": "marketplace"}]
    assert res.data["cached"] is False and again.data["cached"] is True and call.call_count == 1
    sent = call.call_args.args[0]
    assert "office@example.com" in sent.get_header("User-agent") and "countrycodes=pk" in sent.full_url and "q=Liberty+Market" in sent.full_url
    # Another search while the one-a-second slot is taken waits, then gives up rather than exceed the limit.
    safe_cache.add(geocode.SLOT_KEY, 1, timeout=5)
    with _answer(ROWS) as call, mock.patch.object(geocode, "WAIT_SECONDS", 0.3):
        busy = staff.get(SEARCH, {"q": "Hall Road"})
    assert busy.status_code == 429 and busy.data["code"] == "search_busy" and call.call_count == 0
    safe_cache.delete(geocode.SLOT_KEY)
    # Network trouble is a clear message, not a server error.
    with mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
        assert staff.get(SEARCH, {"q": "Anarkali"}).data["code"] == "search_failed"


def test_map_queries_do_not_grow(client_for, people, make_user):
    admin = client_for(people["admin"])

    def count():
        admin.get(MAP)  # warm the settings cache
        with CaptureQueriesContext(connection) as ctx:
            res = admin.get(MAP)
        assert res.status_code == 200
        return len(ctx), len(res.data["visits"])

    def add(i):
        person = make_user(f"p{i}@test.com")
        company = Company.objects.create(name=f"C{i}", assigned_to=person, latitude=LAHORE[0], longitude=LAHORE[1])
        Contact.objects.create(first_name=f"P{i}", assigned_to=person, latitude=LAHORE[0], longitude=LAHORE[1])
        Vendor.objects.create(name=f"V{i}", phone=f"0300 12345{i:02d}", latitude=LAHORE[0], longitude=LAHORE[1])
        v = _visit(person, company=company)
        v.companions.add(people["staff"])
        VisitCheck.objects.create(visit=v, user=person, checked_in_at=timezone.now(), in_location="recorded", in_latitude=LAHORE[0], in_longitude=LAHORE[1])
        VisitCheck.objects.create(visit=v, user=people["staff"], checked_in_at=timezone.now(), in_location="declined")

    add(0)
    small = count()
    for i in range(1, 7):
        add(i)
    grown = count()
    assert grown[0] == small[0] and grown[1] > small[1]


def test_seed_puts_places_around_lahore(db):
    from django.core.management import call_command

    call_command("seed_demo", stdout=io.StringIO())
    for model in (Company, Contact, Vendor):
        pinned = model.objects.filter(latitude__isnull=False)
        assert pinned.exists()
        assert all(Decimal("31.3") < p.latitude < Decimal("31.7") and Decimal("74.1") < p.longitude < Decimal("74.5") for p in pinned)
