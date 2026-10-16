"""Supplies: items and stock per role, stock changes with history and audit, low-stock alerts (once per drop,
preferences respected), purchase requests (approve per department, receive into stock, cancel), the dashboard."""
import pytest
from django.core import mail

from apps.core.models import AuditLog
from apps.inventory.models import PurchaseRequest, StockMovement, SupplyItem
from apps.notifications.models import Notification, NotificationPreference

pytestmark = pytest.mark.django_db

ITEMS = "/api/v1/inventory/items/"
REQUESTS = "/api/v1/inventory/requests/"


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {
        "admin": admin, "manager": manager, "staff": staff,
        "colleague": make_user("colleague@test.com", full_name="Sara Colleague", language="ur"),
        "ops": make_user("ops.person@test.com", department="ops", full_name="Omar Ops"),
        "ops_manager": make_user("ops.manager@test.com", role="manager", department="ops", full_name="Olga Manager"),
    }


@pytest.fixture
def paper(people):
    return SupplyItem.objects.create(name="A4 paper", name_ur="اے فور کاغذ", unit="ream", quantity=12, reorder_level=5)


# ================================================================ items and stock


def test_items_per_role(client_for, people, paper):
    staff, manager, admin = (client_for(people[k]) for k in ("staff", "manager", "admin"))
    assert [i["name"] for i in staff.get(ITEMS).data] == ["A4 paper"]
    assert staff.post(ITEMS, {"name": "Pens"}, format="json").status_code == 403
    assert staff.post(f"{ITEMS}{paper.pk}/stock/", {"kind": "used", "amount": 1}, format="json").status_code == 403
    res = manager.post(ITEMS, {"name": "Toner", "unit": "cartridge", "quantity": 3, "reorder_level": 1, "category": "printing"}, format="json")
    assert res.status_code == 201 and res.data["quantity"] == 3
    toner = SupplyItem.objects.get(name="Toner")
    assert toner.movements.get().kind == "adjusted"  # the opening count is in the history
    # The count isn't edited directly (it has a history); other fields are.
    res = manager.patch(f"{ITEMS}{toner.pk}/", {"quantity": 99, "location": "Store room"}, format="json")
    assert res.data["quantity"] == 3 and res.data["location"] == "Store room"
    assert manager.delete(f"{ITEMS}{toner.pk}/").status_code == 403  # admins delete
    assert admin.delete(f"{ITEMS}{toner.pk}/").status_code == 400  # it has a history: deactivate instead
    assert admin.patch(f"{ITEMS}{toner.pk}/", {"is_active": False}, format="json").status_code == 200
    assert [i["name"] for i in staff.get(ITEMS).data] == ["A4 paper"]
    assert len(admin.get(ITEMS, {"inactive": 1}).data) == 2


def test_stock_changes_history_and_audit(client_for, people, paper):
    manager = client_for(people["manager"])
    stock = f"{ITEMS}{paper.pk}/stock/"
    assert manager.post(stock, {"kind": "used", "amount": 13}, format="json").status_code == 400  # only 12
    assert manager.post(stock, {"kind": "used", "amount": 0}, format="json").status_code == 400
    assert manager.post(stock, {"kind": "used", "amount": 2, "note": "Printer room"}, format="json").data["quantity"] == 10
    assert manager.post(stock, {"kind": "received", "amount": 5}, format="json").data["quantity"] == 15
    assert manager.post(stock, {"kind": "adjusted", "amount": 14}, format="json").data["quantity"] == 14
    history = manager.get(f"{ITEMS}{paper.pk}/history/").data
    assert [(h["kind"], h["change"], h["quantity_after"]) for h in history] == [("adjusted", -1, 14), ("received", 5, 15), ("used", -2, 10)]
    entry = AuditLog.objects.filter(description="Stock updated").first()
    assert entry.changes == {"quantity": [15, 14]} and entry.actor == people["manager"]


def test_low_stock_alert_once_per_drop(client_for, people, paper, django_capture_on_commit_callbacks):
    NotificationPreference.objects.create(user=people["admin"], type="low_stock", in_app=True, email=True)
    manager = client_for(people["manager"])
    stock = f"{ITEMS}{paper.pk}/stock/"
    with django_capture_on_commit_callbacks(execute=True):
        manager.post(stock, {"kind": "used", "amount": 6}, format="json")  # 12 → 6: still above 5
    assert not Notification.objects.filter(type="low_stock").exists()
    with django_capture_on_commit_callbacks(execute=True):
        manager.post(stock, {"kind": "used", "amount": 2}, format="json")  # 6 → 4: alert
    with django_capture_on_commit_callbacks(execute=True):
        manager.post(stock, {"kind": "used", "amount": 1}, format="json")  # 4 → 3: already low, no second alert
    alerts = Notification.objects.filter(type="low_stock")
    # Admins and managers look after supplies (not the person who took them out); staff aren't told.
    assert sorted(alerts.values_list("recipient__email", flat=True)) == ["admin@test.com", "ops.manager@test.com"]
    assert [m.to for m in mail.outbox] == [["admin@test.com"]]  # email only where switched on
    assert "4 ream left" in alerts.get(recipient=people["admin"]).body
    with django_capture_on_commit_callbacks(execute=True):
        manager.post(stock, {"kind": "received", "amount": 10}, format="json")  # back above
        manager.post(stock, {"kind": "used", "amount": 9}, format="json")  # 13 → 4: a new drop, alerted again
    assert Notification.objects.filter(type="low_stock").count() == 4
    assert [i["name"] for i in client_for(people["staff"]).get(ITEMS, {"low": 1}).data] == ["A4 paper"]


# ================================================================ purchase requests


def test_purchase_request_flow(client_for, people, paper, django_capture_on_commit_callbacks):
    staff, colleague, manager, ops_manager = (client_for(people[k]) for k in ("staff", "colleague", "manager", "ops_manager"))
    with django_capture_on_commit_callbacks(execute=True):
        res = colleague.post(REQUESTS, {"item": paper.pk, "quantity": 10, "reason": "Month end printing"}, format="json")
    assert res.status_code == 201 and res.data["status"] == "pending" and res.data["unit"] == "ream"
    pk = res.data["id"]
    ask = Notification.objects.get(type="approval_request")
    assert ask.recipient == people["manager"] and ask.title == "Sara Colleague asks to buy supplies"
    # Staff see only their own; managers and admins see all.
    assert staff.get(REQUESTS).data["results"] == [] and len(manager.get(REQUESTS, {"scope": "all"}).data["results"]) == 1
    assert staff.get(f"{REQUESTS}{pk}/").status_code == 404
    assert ops_manager.post(f"{REQUESTS}{pk}/decide/", {"approve": True}, format="json").status_code == 403  # other department
    assert colleague.post(f"{REQUESTS}{pk}/receive/", {}, format="json").status_code == 403
    with django_capture_on_commit_callbacks(execute=True):
        res = manager.post(f"{REQUESTS}{pk}/decide/", {"approve": True, "note": "Buy from the usual shop"}, format="json")
    assert res.data["status"] == "approved"
    approved = Notification.objects.get(type="approval_result", recipient=people["colleague"])
    assert approved.title == "خریداری کی درخواست منظور ہو گئی" and "اے فور کاغذ" in approved.body  # in the reader's language
    with django_capture_on_commit_callbacks(execute=True):
        res = ops_manager.post(f"{REQUESTS}{pk}/receive/", {"quantity": 8}, format="json")  # any supply manager receives
    assert res.data["status"] == "received" and res.data["received_quantity"] == 8
    paper.refresh_from_db()
    assert paper.quantity == 20 and paper.movements.get().purchase_request_id == pk
    assert manager.post(f"{REQUESTS}{pk}/cancel/").status_code == 403  # done
    assert AuditLog.objects.filter(object_id=str(pk), changes__status=["approved", "received"]).exists()


def test_new_items_rejections_and_cancelling(client_for, people, django_capture_on_commit_callbacks):
    staff, manager, admin = (client_for(people[k]) for k in ("staff", "manager", "admin"))
    assert staff.post(REQUESTS, {"quantity": 2}, format="json").status_code == 400  # say what
    new = staff.post(REQUESTS, {"item_name": "Desk fan", "quantity": 2, "unit": "piece", "estimated_cost": "9000"}, format="json").data
    assert admin.post(f"{REQUESTS}{new['id']}/decide/", {"approve": True}, format="json").status_code == 200
    assert admin.post(f"{REQUESTS}{new['id']}/receive/", {}, format="json").status_code == 200
    fan = SupplyItem.objects.get(name="Desk fan")  # received as a new item in the list
    assert fan.quantity == 2 and fan.category == "other"

    gone = staff.post(REQUESTS, {"item_name": "Coffee", "quantity": 1}, format="json").data
    assert staff.post(f"{REQUESTS}{gone['id']}/cancel/").status_code == 200
    no = staff.post(REQUESTS, {"item_name": "Sofa", "quantity": 1}, format="json").data
    with django_capture_on_commit_callbacks(execute=True):
        res = manager.post(f"{REQUESTS}{no['id']}/decide/", {"approve": False, "note": "Not this year"}, format="json")
    assert res.data["status"] == "rejected"
    assert "Not this year" in Notification.objects.get(title="Purchase request not approved").body
    # An admin's own request is approved at once; a manager's own goes to the admins.
    assert admin.post(REQUESTS, {"item_name": "Kettle", "quantity": 1}, format="json").data["status"] == "approved"
    mine = manager.post(REQUESTS, {"item_name": "Whiteboard", "quantity": 1}, format="json").data
    assert manager.post(f"{REQUESTS}{mine['id']}/decide/", {"approve": True}, format="json").status_code == 403
    assert [r["id"] for r in admin.get(REQUESTS, {"scope": "approvals"}).data["results"]] == [mine["id"]]
    assert PurchaseRequest.objects.filter(status="cancelled").count() == 1


def test_seed_creates_supplies(db):
    import io

    from django.core.management import call_command

    call_command("seed_demo", stdout=io.StringIO())
    assert SupplyItem.objects.count() >= 8 and any(i.is_low for i in SupplyItem.objects.all())
    assert StockMovement.objects.exists()
    assert set(PurchaseRequest.objects.values_list("status", flat=True)) >= {"pending", "approved", "received"}
