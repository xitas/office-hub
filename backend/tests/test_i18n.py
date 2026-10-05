"""Backend-generated text follows the reader's language (Accept-Language, sent by the frontend)."""
import pytest
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator

from apps.core.ws_auth import issue_ticket
from apps.notifications.models import Notification
from config.asgi import application

pytestmark = pytest.mark.django_db

UR = {"HTTP_ACCEPT_LANGUAGE": "ur"}
EN = {"HTTP_ACCEPT_LANGUAGE": "en"}


def test_notification_text_follows_reader_language(client_for, admin, staff):
    staff.language = "ur"
    staff.save()
    client_for(admin).patch(f"/api/v1/users/{staff.pk}/", {"role": "manager"}, format="json")

    # Stored fallback text is in the recipient's saved language.
    n = Notification.objects.get(recipient=staff)
    assert n.message_key == "account_updated"
    assert n.title == "آپ کا اکاؤنٹ اپ ڈیٹ ہو گیا"

    c = client_for(staff)
    ur = c.get("/api/v1/notifications/", **UR).data["results"][0]
    assert ur["title"] == "آپ کا اکاؤنٹ اپ ڈیٹ ہو گیا"
    assert "کردار اب مینیجر ہے" in ur["body"] and admin.full_name in ur["body"]

    # Switching the UI language re-renders old notifications too.
    en = c.get("/api/v1/notifications/", **EN).data["results"][0]
    assert en["title"] == "Your account was updated"
    assert en["body"] == f"{admin.full_name} changed your account: role is now Manager."


def test_department_change_with_no_department_is_translated(client_for, admin, staff):
    client_for(admin).patch(f"/api/v1/users/{staff.pk}/", {"department": None}, format="json")
    body = client_for(staff).get("/api/v1/notifications/", **UR).data["results"][0]["body"]
    assert "شعبہ اب کوئی نہیں ہے" in body


@pytest.mark.django_db(transaction=True)
async def test_live_push_uses_recipient_language(admin, staff):
    staff.language = "ur"
    await database_sync_to_async(staff.save)()
    ws = WebsocketCommunicator(
        application,
        f"/ws/notifications/?ticket={issue_ticket(staff)}",
        headers=[(b"origin", b"http://localhost")],
    )
    assert (await ws.connect())[0]
    await ws.receive_json_from()  # unread_count

    from apps.notifications.services import notify

    await database_sync_to_async(notify)(
        staff, "system", actor=admin, message="account_updated", params={"actor": admin.full_name, "role": "staff"}
    )
    event = await ws.receive_json_from(timeout=2)
    assert event["notification"]["title"] == "آپ کا اکاؤنٹ اپ ڈیٹ ہو گیا"
    assert "عملہ" in event["notification"]["body"]
    await ws.disconnect()


def test_server_errors_are_translated(api, staff, client_for):
    res = api.post("/api/v1/auth/login/", {"email": staff.email, "password": "wrong"}, format="json", **UR)
    assert res.status_code == 401 and res.data["detail"] == "ای میل یا پاس ورڈ غلط ہے۔"

    res = client_for(staff).get("/api/v1/audit-log/", **UR)
    assert res.data["detail"] == "آپ کو یہ عمل کرنے کی اجازت نہیں ہے۔"

    res = api.post("/api/v1/auth/password/reset/confirm/", {}, format="json", **UR)
    assert res.data["detail"] == "براہ کرم نیچے دی گئی غلطیاں درست کریں۔"
    assert res.data["errors"]["uid"] == ["یہ خانہ درکار ہے۔"]

    # Default stays English.
    res = api.post("/api/v1/auth/login/", {"email": staff.email, "password": "wrong"}, format="json", **EN)
    assert res.data["detail"] == "Invalid email or password."


def test_audit_labels_are_translated(client_for, admin, staff):
    client_for(admin).patch(f"/api/v1/users/{staff.pk}/", {"job_title": "Lead"}, format="json")
    entry = client_for(admin).get("/api/v1/audit-log/", {"action": "update"}, **UR).data["results"][0]
    assert entry["action_label"] == "ترمیم کی گئی"
    assert entry["model"] == "user" and entry["model_label"] == "صارف"

    feed = client_for(admin).get("/api/v1/dashboard/", **UR).data["activity"]
    assert feed[0]["model_label"] == "صارف"


def test_failed_login_audit_description_translated_on_read(api, client_for, admin, staff):
    api.post("/api/v1/auth/login/", {"email": "ghost@test.com", "password": "x"}, format="json")
    en = client_for(admin).get("/api/v1/audit-log/", {"action": "login_failed"}, **EN).data["results"][0]
    assert en["description"] == "Failed sign-in attempt" and en["object_repr"] == "ghost@test.com"
    ur = client_for(admin).get("/api/v1/audit-log/", {"action": "login_failed"}, **UR).data["results"][0]
    assert ur["description"] == "سائن اِن کی ناکام کوشش"
