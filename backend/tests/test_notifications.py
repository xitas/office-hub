import pytest
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.core import mail
from rest_framework_simplejwt.tokens import AccessToken

from apps.notifications.models import Notification, NotificationPreference
from apps.notifications.services import notify
from config.asgi import application


@pytest.mark.django_db
def test_notify_respects_preferences(manager, staff):
    # Defaults: task_assigned -> in-app + email; mention -> in-app only.
    notify(staff, "task_assigned", "New task", body="Call the client", link="/tasks/1", actor=manager)
    notify(staff, "mention", "You were mentioned", actor=manager)
    assert Notification.objects.filter(recipient=staff).count() == 2
    assert len(mail.outbox) == 1 and mail.outbox[0].subject == "New task"

    NotificationPreference.objects.create(user=staff, type="task_assigned", in_app=False, email=False)
    notify([staff], "task_assigned", "Another task", actor=manager)
    assert Notification.objects.filter(recipient=staff).count() == 2
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_role_change_notifies_the_user(client_for, admin, staff):
    client_for(admin).patch(f"/api/v1/users/{staff.pk}/", {"role": "manager"}, format="json")
    n = Notification.objects.get(recipient=staff)
    assert n.type == "system" and "Manager" in n.body and n.actor == admin
    # Cosmetic edits don't notify.
    client_for(admin).patch(f"/api/v1/users/{staff.pk}/", {"phone": "123"}, format="json")
    assert Notification.objects.filter(recipient=staff).count() == 1


@pytest.mark.django_db
def test_actor_is_not_notified_about_own_action(staff):
    assert notify([staff], "task_status", "Moved", actor=staff) == []


@pytest.mark.django_db
def test_notification_endpoints(client_for, staff, manager):
    notify(staff, "mention", "One", actor=manager)
    n2 = notify(staff, "mention", "Two", actor=manager)[0]
    notify(manager, "mention", "Not mine", actor=staff)
    c = client_for(staff)

    assert c.get("/api/v1/notifications/").data["count"] == 2
    assert c.get("/api/v1/notifications/unread-count/").data["count"] == 2
    assert c.post(f"/api/v1/notifications/{n2.pk}/read/").data["is_read"] is True
    assert c.post("/api/v1/notifications/read-all/").data["updated"] == 1
    assert c.get("/api/v1/notifications/unread-count/").data["count"] == 0

    prefs = c.get("/api/v1/notifications/preferences/").data
    assert {p["type"] for p in prefs} >= {"task_assigned", "mention", "announcement"}
    res = c.put(
        "/api/v1/notifications/preferences/", [{"type": "mention", "in_app": True, "email": True}], format="json"
    )
    assert next(p for p in res.data if p["type"] == "mention")["email"] is True


@pytest.mark.django_db(transaction=True)
async def test_websocket_requires_token_and_receives_push(staff, manager):
    anon = WebsocketCommunicator(application, "/ws/notifications/", headers=[(b"origin", b"http://localhost")])
    connected, code = await anon.connect()
    assert not connected

    token = str(AccessToken.for_user(staff))
    ws = WebsocketCommunicator(
        application, f"/ws/notifications/?token={token}", headers=[(b"origin", b"http://localhost")]
    )
    connected, _ = await ws.connect()
    assert connected
    assert await ws.receive_json_from() == {"type": "unread_count", "count": 0}

    await database_sync_to_async(notify)(staff, "mention", "Hello live", actor=manager)
    event = await ws.receive_json_from(timeout=2)
    assert event["type"] == "notification" and event["notification"]["title"] == "Hello live"
    await ws.disconnect()
