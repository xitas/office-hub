"""Vendors: the shared directory per role (preferred/inactive for managers and admins, categories for admins),
the new-vendor notification, phone search in any format, and the connections to supplies, purchase requests,
expenses, the timeline (calls, follow-ups, the communication log) and message templates; query counts; seed."""
import io
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.core.models import AuditLog
from apps.core.office_time import office_today
from apps.expenses.models import Expense
from apps.inventory.models import PurchaseRequest, SupplyItem
from apps.message_templates.models import MessageTemplate
from apps.notifications.models import Notification, NotificationPreference
from apps.tasks.models import Task
from apps.timeline.models import TimelineEntry
from apps.vendors.models import Vendor, VendorCategory

pytestmark = pytest.mark.django_db

URL = "/api/v1/vendors/"
CATS = "/api/v1/vendors/categories/"


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {
        "admin": admin, "manager": manager, "staff": staff,
        "colleague": make_user("colleague@test.com", full_name="Sara Colleague", language="ur"),
        "ops_manager": make_user("ops.manager@test.com", role="manager", department="ops", full_name="Olga Manager"),
    }


@pytest.fixture
def stationery(db):
    return VendorCategory.objects.create(name="Stationery", name_ur="اسٹیشنری")


@pytest.fixture
def printer(people, stationery):
    v = Vendor.objects.create(name="Al-Noor Printers", contact_person="Imran Butt", phone="0300-1112233", city="Lahore",
                              areas="Gulberg, Model Town", email="sales@alnoor.test")
    v.categories.set([stationery])
    return v


# ================================================================ directory per role


def test_directory_per_role(client_for, people, stationery, django_capture_on_commit_callbacks):
    staff, manager, admin = (client_for(people[k]) for k in ("staff", "manager", "admin"))
    NotificationPreference.objects.create(user=people["ops_manager"], type="vendor", in_app=True, email=True)
    assert staff.post(URL, {"name": "No way to reach"}, format="json").status_code == 400  # a phone, email or address
    assert staff.post(URL, {"name": "Shop", "phone": "042 111", "preferred": True}, format="json").status_code == 400
    with django_capture_on_commit_callbacks(execute=True):
        res = staff.post(URL, {"name": "City Couriers", "phone": "0321 5556677", "city": "Lahore", "categories": [stationery.pk]}, format="json")
    assert res.status_code == 201 and not res.data["can_curate"]
    pk = res.data["id"]
    told = Notification.objects.filter(type="vendor")
    # Managers and admins (who look after supplies) hear about it, in their language; not the person who added it.
    assert sorted(told.values_list("recipient__email", flat=True)) == ["admin@test.com", "manager@test.com", "ops.manager@test.com"]
    assert told.get(recipient=people["admin"]).title == "New vendor: City Couriers" and "Stationery" in told.get(recipient=people["admin"]).body
    assert [m.to for m in mail.outbox] == [["ops.manager@test.com"]]  # email where switched on
    assert staff.patch(f"{URL}{pk}/", {"contact_person": "Bilal"}, format="json").status_code == 200  # anyone corrects details
    assert staff.patch(f"{URL}{pk}/", {"is_active": False}, format="json").status_code == 400
    assert staff.delete(f"{URL}{pk}/").status_code == 403
    assert manager.patch(f"{URL}{pk}/", {"preferred": True, "rating": 4}, format="json").data["preferred"] is True
    assert manager.patch(f"{URL}{pk}/", {"rating": 6}, format="json").status_code == 400
    entry = AuditLog.objects.filter(object_id=str(pk), action="update").order_by("id").first()
    assert entry.changes == {"contact_person": ["", "Bilal"]}
    # Categories: everyone sees the active ones, admins manage them; a used one is made inactive, not deleted.
    assert staff.post(CATS, {"name": "Plumbers"}, format="json").status_code == 403
    assert admin.post(CATS, {"name": "Plumbers", "name_ur": "پلمبر"}, format="json").status_code == 201
    assert admin.delete(f"{CATS}{stationery.pk}/").status_code == 403
    assert [c["name"] for c in staff.get(CATS).data] == ["Plumbers", "Stationery"]
    # Inactive vendors drop out of the list (managers can still show them); deleting one in use is refused.
    TimelineEntry.objects.create(kind="note", vendor_id=pk, summary="Asked for rates", created_by=people["staff"])
    assert manager.delete(f"{URL}{pk}/").status_code == 400
    assert manager.patch(f"{URL}{pk}/", {"is_active": False}, format="json").status_code == 200
    assert staff.get(URL).data["results"] == []
    assert len(manager.get(URL, {"inactive": 1}).data["results"]) == 1


def test_search_and_filters(client_for, people, printer, stationery):
    staff = client_for(people["staff"])
    Vendor.objects.create(name="Bright Cleaners", phone="+92 42 3577 8899", city="Karachi")
    names = lambda **p: [v["name"] for v in staff.get(URL, p).data["results"]]  # noqa: E731
    assert names(q="+92 300 111") == ["Al-Noor Printers"]  # any phone format
    assert names(q="model town") == ["Al-Noor Printers"]  # areas served
    assert names(category=stationery.pk) == ["Al-Noor Printers"] and names(city="karachi") == ["Bright Cleaners"]
    assert staff.get(f"{URL}cities/").data == ["Karachi", "Lahore"]
    found = staff.get("/api/v1/search/", {"q": "0300-1112"}).data["results"]
    assert [r["title"] for r in found["vendors"]] == ["Al-Noor Printers"] and found["vendors"][0]["url"] == f"/vendors/{printer.pk}"


# ================================================================ supplies, purchases and expenses


def test_supplies_purchases_and_expenses(client_for, people, printer, django_capture_on_commit_callbacks):
    staff, colleague, manager, admin = (client_for(people[k]) for k in ("staff", "colleague", "manager", "admin"))
    paper = SupplyItem.objects.create(name="A4 paper", unit="ream", quantity=20, reorder_level=5)
    assert manager.patch(f"/api/v1/inventory/items/{paper.pk}/", {"supplier": printer.pk}, format="json").data["supplier_name"] == "Al-Noor Printers"
    assert [i["name"] for i in staff.get("/api/v1/inventory/items/", {"supplier": printer.pk}).data] == ["A4 paper"]
    # A request for the item goes to its usual supplier unless another is named; receiving records where it was bought.
    req = staff.post("/api/v1/inventory/requests/", {"item": paper.pk, "quantity": 5}, format="json").data
    assert req["vendor"] == printer.pk and req["vendor_name"] == "Al-Noor Printers"
    other = Vendor.objects.create(name="Hall Road Traders", phone="0333 0000000")
    new = staff.post("/api/v1/inventory/requests/", {"item_name": "Desk lamp", "quantity": 1}, format="json").data
    admin.post(f"/api/v1/inventory/requests/{new['id']}/decide/", {"approve": True}, format="json")
    res = admin.post(f"/api/v1/inventory/requests/{new['id']}/receive/", {"vendor": other.pk}, format="json")
    assert res.data["vendor"] == other.pk and SupplyItem.objects.get(name="Desk lamp").supplier == other
    # Expense claims name who was paid.
    form = {"title": "Visiting cards", "category": "supplies", "amount": "2500", "spent_on": office_today().isoformat(), "vendor": printer.pk}
    mine = staff.post("/api/v1/expenses/claims/", form, format="json").data
    assert mine["vendor_name"] == "Al-Noor Printers"
    colleague.post("/api/v1/expenses/claims/", {**form, "amount": "900", "title": "Flyers"}, format="json")
    for e in Expense.objects.all():
        manager.post(f"/api/v1/expenses/claims/{e.pk}/decide/", {"approve": True}, format="json")
    # The vendor's activity shows only what each person may see.
    staff_view = staff.get(f"{URL}{printer.pk}/activity/").data
    assert [s["name"] for s in staff_view["supplies"]] == ["A4 paper"]
    assert [p["id"] for p in staff_view["purchases"]] == [req["id"]]  # their own request
    assert [e["title"] for e in staff_view["expenses"]["recent"]] == ["Visiting cards"] and staff_view["expenses"]["year_total"] == "2500.00"
    manager_view = manager.get(f"{URL}{printer.pk}/activity/").data
    assert manager_view["expenses"]["year_total"] == "3400.00" and len(manager_view["purchases"]) == 1


# ================================================================ timeline and templates


def test_timeline_follow_ups_and_templates(client_for, people, printer):
    staff = client_for(people["staff"])
    tomorrow = (office_today() + timedelta(days=1)).isoformat()
    res = staff.post("/api/v1/timeline/", {
        "kind": "call", "vendor": printer.pk, "summary": "Asked for the new rate card", "details": {"direction": "out", "outcome": "connected"},
        "follow_up_on": tomorrow,
    }, format="json")
    assert res.status_code == 201 and res.data["vendor"] == {"id": printer.pk, "name": "Al-Noor Printers"}
    assert staff.post("/api/v1/timeline/", {"kind": "note", "vendor": printer.pk, "contact": None, "company": None, "summary": "x"},
                      format="json").status_code == 201
    task = Task.objects.get(follow_up_of__vendor=printer)
    assert task.title == "Follow up with Al-Noor Printers: Asked for the new rate card"
    timeline = staff.get("/api/v1/timeline/", {"vendor": printer.pk}).data["results"]
    assert [e["kind"] for e in timeline] == ["note", "call"]
    log = staff.get("/api/v1/timeline/log/", {"vendor": printer.pk}).data["results"]
    assert len(log) == 2 and log[0]["vendor"]["name"] == "Al-Noor Printers"
    dashboard = staff.get("/api/v1/dashboard/").data
    assert dashboard["follow_ups_due"][0]["title"] == "Al-Noor Printers"
    assert not [a for a in dashboard["client_activity"] if a.get("vendor")]  # suppliers aren't client activity
    # Templates fill from the vendor: its contact person stands in for the contact, the vendor for the company.
    tpl = MessageTemplate.objects.create(name="Order", body="Dear {contact.first_name}, please send 10 reams to {org.name}. ({contact.company})",
                                         channel="whatsapp", created_by=people["staff"])
    filled = staff.post(f"/api/v1/templates/{tpl.pk}/fill/", {"vendor": printer.pk}, format="json").data
    assert filled["body"].startswith("Dear Imran, please send 10 reams") and "(Al-Noor Printers)" in filled["body"]
    assert filled["whatsapp_url"].startswith("https://wa.me/923001112233")


# ================================================================ query counts and seed


def test_vendor_endpoints_do_not_grow(client_for, people, stationery, make_user):
    manager = client_for(people["manager"])

    def counts(vendor):
        out = []
        for url, params in ((URL, {}), (f"{URL}{vendor.pk}/activity/", {}), ("/api/v1/timeline/", {"vendor": vendor.pk}),
                            (CATS, {}), (f"{URL}cities/", {})):
            with CaptureQueriesContext(connection) as ctx:
                assert manager.get(url, params).status_code == 200
            out.append(len(ctx))
        return out

    def add(i):
        person = make_user(f"p{i}@test.com")
        v = Vendor.objects.create(name=f"Vendor {i}", phone=f"0300 00000{i:02d}", city=f"City {i % 3}")
        v.categories.set([stationery])
        first = Vendor.objects.order_by("pk").first()
        SupplyItem.objects.create(name=f"Item {i}", supplier=first)
        PurchaseRequest.objects.create(item_name=f"Item {i}", quantity=1, vendor=first, requested_by=person)
        Expense.objects.create(user=person, title=f"E{i}", category="other", amount=Decimal("10"), currency="PKR",
                               spent_on=office_today(), vendor=first, status="approved")
        TimelineEntry.objects.create(kind="note", vendor=first, summary=f"Note {i}", created_by=person)

    add(0)
    vendor = Vendor.objects.order_by("pk").first()
    small = counts(vendor)
    for i in range(1, 8):
        add(i)
    assert counts(vendor) == small


def test_seed_creates_vendors(db):
    from django.core.management import call_command

    call_command("seed_demo", stdout=io.StringIO())
    assert Vendor.objects.count() >= 8 and VendorCategory.objects.count() >= 6
    assert SupplyItem.objects.filter(supplier__isnull=False).exists()
    assert PurchaseRequest.objects.filter(vendor__isnull=False).exists() and Expense.objects.filter(vendor__isnull=False).exists()
    assert TimelineEntry.objects.filter(vendor__isnull=False).exists()
    assert not Notification.objects.filter(type="vendor").exists()  # seeding is quiet
