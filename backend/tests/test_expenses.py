"""Expenses: claims with receipts (task-file rules, private downloads), who sees and decides them, paying,
editing and cancelling, notifications in each reader's language, audit, the month summary, and the combined
"Pending approvals" widget (one query for leave, bookings, expenses and purchase requests)."""
import io
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from PIL import Image

from apps.core.models import AuditLog
from apps.core.office_time import office_today
from apps.dashboard import approvals
from apps.expenses.models import Expense
from apps.inventory.models import PurchaseRequest
from apps.leave.models import LeaveRequest, LeaveType
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db

URL = "/api/v1/expenses/claims/"


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {
        "admin": admin, "manager": manager, "staff": staff,
        "colleague": make_user("colleague@test.com", full_name="Sara Colleague", language="ur"),
        "ops": make_user("ops.person@test.com", department="ops", full_name="Omar Ops"),
        "ops_manager": make_user("ops.manager@test.com", role="manager", department="ops", full_name="Olga Manager"),
    }


def _png(name="receipt.png"):
    buf = io.BytesIO()
    Image.new("RGB", (60, 90), "white").save(buf, "PNG")
    buf.seek(0)
    buf.name = name
    return buf


def claim(client, files=(), **data):
    body = {"title": "Taxi to client", "category": "travel", "amount": "1250.50", "spent_on": office_today().isoformat(), **data}
    if files:
        return client.post(URL, {**body, "files": list(files)})  # multipart
    return client.post(URL, body, format="json")


# ================================================================ claims and receipts


def test_claim_with_receipts_and_private_downloads(client_for, people, django_capture_on_commit_callbacks):
    staff = client_for(people["staff"])
    fake = io.BytesIO(b"MZ not a pdf")
    fake.name = "bill.pdf"
    assert claim(staff, files=[fake]).status_code == 400 and not Expense.objects.exists()  # all or nothing
    assert claim(staff, spent_on=(office_today() + timedelta(days=1)).isoformat()).status_code == 400
    assert claim(staff, spent_on=(office_today() - timedelta(days=400)).isoformat()).status_code == 400
    assert claim(staff, amount="0").status_code == 400
    with django_capture_on_commit_callbacks(execute=True):
        res = claim(staff, files=[_png()])
    assert res.status_code == 201 and res.data["status"] == "pending" and res.data["currency"] == "PKR"
    receipt = res.data["receipts"][0]
    assert receipt["kind"] == "image" and receipt["thumbnail_url"]
    ask = Notification.objects.get(type="approval_request")
    assert ask.recipient == people["manager"] and ask.body == f"Taxi to client · PKR 1,250.50 · {office_today():%d/%m/%Y}"
    url = f"/api/v1{receipt['download_url']}"
    assert client_for(people["manager"]).get(f"/api/v1{receipt['thumbnail_url']}").status_code == 200
    assert client_for(people["colleague"]).get(url).status_code == 404  # claims are private
    assert client_for(people["ops_manager"]).get(url).status_code == 404
    entry = AuditLog.objects.get(action="create", content_type__model="expense")
    assert entry.changes["receipts"] == [None, "receipt.png"]


def test_who_sees_decides_and_pays(client_for, people, django_capture_on_commit_callbacks):
    staff, colleague, manager, ops_manager, admin = (
        client_for(people[k]) for k in ("staff", "colleague", "manager", "ops_manager", "admin"))
    pk = claim(colleague, title="Lunch with client", category="client", amount="3200").data["id"]
    assert staff.get(f"{URL}{pk}/").status_code == 404
    assert [e["id"] for e in manager.get(URL, {"scope": "team"}).data] == [pk]
    assert ops_manager.get(URL, {"scope": "team"}).data == []
    assert ops_manager.post(f"{URL}{pk}/decide/", {"approve": True}, format="json").status_code == 404
    assert colleague.post(f"{URL}{pk}/decide/", {"approve": True}, format="json").status_code == 403
    assert manager.post(f"{URL}{pk}/pay/", {}, format="json").status_code == 403  # not approved, and only admins pay
    with django_capture_on_commit_callbacks(execute=True):
        assert manager.post(f"{URL}{pk}/decide/", {"approve": True}, format="json").data["status"] == "approved"
    note = Notification.objects.get(type="approval_result", recipient=people["colleague"])
    assert note.title == "اخراجات منظور ہو گئے" and "PKR 3,200" in note.body  # Urdu reader, Latin digits
    assert colleague.patch(f"{URL}{pk}/", {"amount": "1"}, format="json").status_code == 403  # no edits once decided
    assert manager.post(f"{URL}{pk}/pay/", {}, format="json").status_code == 403
    assert [e["id"] for e in admin.get(URL, {"scope": "to_pay"}).data] == [pk]
    with django_capture_on_commit_callbacks(execute=True):
        res = admin.post(f"{URL}{pk}/pay/", {"note": "Bank transfer 1182"}, format="json")
    assert res.data["status"] == "paid" and res.data["paid_by_name"] == "Admin"
    paid = Notification.objects.filter(recipient=people["colleague"]).order_by("-id").first()
    assert "Bank transfer 1182" in paid.body
    assert any("Bank transfer 1182" in m.body for m in mail.outbox)  # approval results email by default
    statuses = [e.changes["status"] for e in AuditLog.objects.filter(object_id=str(pk), action="update").order_by("id")]
    assert statuses == [["pending", "approved"], ["approved", "paid"]]


def test_edit_cancel_reject_and_own_claims(client_for, people, django_capture_on_commit_callbacks):
    staff, manager, admin = (client_for(people[k]) for k in ("staff", "manager", "admin"))
    res = claim(staff, files=[_png("a.png"), _png("b.png")])
    pk, (keep, drop) = res.data["id"], res.data["receipts"]
    res = staff.patch(f"{URL}{pk}/", {"amount": "990", "remove_receipts": [drop["id"]]}, format="json")
    assert res.data["amount"] == "990.00" and [r["id"] for r in res.data["receipts"]] == [keep["id"]]
    assert manager.patch(f"{URL}{pk}/", {"amount": "1"}, format="json").status_code == 403  # the claimant edits
    assert staff.post(f"{URL}{pk}/cancel/").data["status"] == "cancelled"

    no = claim(staff, title="Gym").data["id"]
    with django_capture_on_commit_callbacks(execute=True):
        manager.post(f"{URL}{no}/decide/", {"approve": False, "note": "Not an office expense"}, format="json")
    assert "Not an office expense" in Notification.objects.get(title="Expense not approved").body
    # A manager's own claim goes to the admins; an admin's own to the other admins (at once only if there are none).
    mine = claim(manager).data
    assert mine["status"] == "pending" and not mine["can_decide"]
    assert [e["id"] for e in admin.get(URL, {"scope": "approvals"}).data] == [mine["id"]]
    assert claim(admin).data["status"] == "approved"


def test_month_summary(client_for, people):
    staff, manager = client_for(people["staff"]), client_for(people["manager"])
    today = office_today()
    for amount, category in (("100", "travel"), ("250.50", "meals"), ("40", "travel")):
        claim(staff, amount=amount, category=category)
    ids = list(Expense.objects.order_by("id").values_list("pk", flat=True))
    manager.post(f"{URL}{ids[0]}/decide/", {"approve": True}, format="json")
    manager.post(f"{URL}{ids[1]}/decide/", {"approve": True}, format="json")
    data = staff.get(f"{URL}summary/", {"month": today.strftime("%Y-%m")}).data
    assert data["by_status"]["approved"] == {"count": 2, "amount": "350.50"}
    assert data["by_status"]["pending"] == {"count": 1, "amount": "40.00"}
    assert data["by_category"] == {"travel": "100.00", "meals": "250.50"}
    assert manager.get(f"{URL}summary/", {"scope": "team"}).data["by_status"]["approved"]["count"] == 2
    assert staff.get(f"{URL}summary/", {"month": "2026-13"}).status_code == 400


# ================================================================ dashboard


def test_pending_approvals_widget_is_one_query(client_for, people):
    staff, colleague = people["staff"], people["colleague"]
    annual = LeaveType.objects.create(name="Annual", name_ur="سالانہ", days_per_year=Decimal("10"))
    day = office_today() + timedelta(days=7)
    rows = [
        LeaveRequest.objects.create(user=staff, leave_type=annual, start_date=day, end_date=day, days=1),
        Expense.objects.create(user=colleague, title="Fuel", category="fuel", amount=Decimal("2000"), currency="PKR", spent_on=office_today()),
        PurchaseRequest.objects.create(item_name="Toner", quantity=2, unit="cartridge", requested_by=staff),
    ]
    for hours, row in zip((3, 2, 1), rows):
        type(row).objects.filter(pk=row.pk).update(created_at=timezone.now() - timedelta(hours=hours))
    with CaptureQueriesContext(connection) as ctx:
        items = approvals.pending(people["manager"])
    assert len(ctx) == 1
    assert [i["badge"] for i in items] == ["Leave", "Expense", "Supplies"]  # oldest first
    assert items[1]["subtitle"] == f"Fuel · PKR 2,000 · {office_today():%d/%m/%Y}"
    assert items[2]["subtitle"] == "Toner · 2 cartridge"
    data = client_for(people["manager"]).get("/api/v1/dashboard/", HTTP_ACCEPT_LANGUAGE="ur").data["pending_approvals"]
    assert data[0]["subtitle"].startswith("سالانہ")
    assert approvals.pending(people["ops_manager"]) == [] and approvals.pending(staff) == []


def test_seed_creates_expenses(db):
    from django.core.management import call_command

    call_command("seed_demo", stdout=io.StringIO())
    statuses = set(Expense.objects.values_list("status", flat=True))
    assert statuses >= {"pending", "approved", "paid", "rejected"}
    assert Expense.objects.filter(receipts__isnull=False).exists()


def test_lists_do_not_grow(client_for, people, make_user):
    from apps.inventory.models import SupplyItem

    admin = client_for(people["admin"])

    def count(url, params=None):
        with CaptureQueriesContext(connection) as ctx:
            assert admin.get(url, params or {}).status_code == 200
        return len(ctx)

    def add(i):
        person = make_user(f"p{i}@test.com", department="ops" if i % 2 else "sales")
        claim(client_for(person), files=[_png()], title=f"Claim {i}")
        item = SupplyItem.objects.create(name=f"Item {i}", quantity=i, reorder_level=3)
        PurchaseRequest.objects.create(item=item, item_name=item.name, quantity=1, requested_by=person)

    urls = [(URL, {"scope": "team"}), (URL, {"scope": "approvals"}), (f"{URL}summary/", {"scope": "team"}),
            ("/api/v1/inventory/items/", {}), ("/api/v1/inventory/requests/", {"scope": "all"}),
            ("/api/v1/inventory/requests/", {"scope": "approvals"})]
    add(0)
    small = [count(u, p) for u, p in urls]
    for i in range(1, 8):
        add(i)
    assert [count(u, p) for u, p in urls] == small
