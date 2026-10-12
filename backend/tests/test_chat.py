"""Chat foundations: default channels, visibility, channel management, DMs, history, edit/delete,
read state, live delivery only to members, and the sending rate limit."""
from datetime import timedelta
from unittest import mock

import pytest
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import Department, User
from apps.chat import services
from apps.chat.models import Conversation, Membership, Message
from apps.core.models import AuditLog
from apps.core.ws_auth import issue_ticket
from config.asgi import application

pytestmark = pytest.mark.django_db

CONV = "/api/v1/chat/conversations/"
MSG = "/api/v1/chat/messages/"


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {
        "admin": admin, "manager": manager, "staff": staff,
        "colleague": make_user("colleague@test.com", full_name="Sara Colleague"),
        "outsider": make_user("ops.person@test.com", department="ops", full_name="Omar Ops"),
    }


def general():
    return Conversation.objects.get(is_default=True, channel_type="general")


def dept_channel(name):
    return Conversation.objects.get(is_default=True, channel_type="department", department__name=name)


def channel(name, creator, *, private=False, members=(), department=None, channel_type="project"):
    c = Conversation.objects.create(name=name, is_private=private, created_by=creator, department=department, channel_type=channel_type)
    services.add_members(c, [creator, *members])
    return c


def members_of(conversation):
    return set(conversation.memberships.values_list("user__email", flat=True))


def mine(client):
    return {c["name"] or f"dm:{c['other_person']['full_name']}": c for c in client.get(CONV).data}


# ================================================================ default channels


def test_default_channels_follow_the_organization(people, departments):
    everyone = {u.email for u in people.values()}
    assert members_of(general()) == everyone
    assert members_of(dept_channel("Sales")) == {"manager@test.com", "staff@test.com", "colleague@test.com"}
    assert members_of(dept_channel("Operations")) == {"ops.person@test.com"}
    assert dept_channel("Sales").is_private

    staff = people["staff"]
    staff.department = departments["ops"]
    staff.save()
    assert "staff@test.com" not in members_of(dept_channel("Sales"))
    assert "staff@test.com" in members_of(dept_channel("Operations"))

    staff.is_active = False
    staff.save()
    assert "staff@test.com" not in members_of(general()) | members_of(dept_channel("Operations"))

    hr = Department.objects.create(name="HR")
    assert dept_channel("HR").name == "HR"
    hr.name = "People"
    hr.save()
    assert Conversation.objects.get(department=hr, is_default=True).name == "People"


def test_login_style_saves_do_not_touch_memberships(people):
    with CaptureQueriesContext(connection) as ctx:
        people["staff"].save(update_fields=["last_login"])
    assert len(ctx) == 1


def test_new_member_starts_caught_up(people):
    s = people["staff"]
    services.send_message(general(), s, "Before you joined")
    newcomer = User.objects.create_user(email="new@test.com", password="x", full_name="New Person", role="staff")
    assert services.total_unread(newcomer) == 0


# ================================================================ visibility and permissions


def test_public_channel_can_be_read_and_joined_by_anyone(client_for, people):
    project = channel("Launch", people["manager"], department=people["manager"].department)
    services.send_message(project, people["manager"], "Kick-off on Monday")
    outsider = client_for(people["outsider"])

    browse = {c["name"] for c in outsider.get(CONV, {"scope": "browse"}).data}
    assert "Launch" in browse and "Launch" not in mine(outsider)
    assert outsider.get(f"{CONV}{project.pk}/messages/").data["results"][0]["body"] == "Kick-off on Monday"
    assert outsider.post(f"{CONV}{project.pk}/messages/", {"body": "Hi"}).status_code == 403  # join first

    assert outsider.post(f"{CONV}{project.pk}/join/").data["is_member"] is True
    assert outsider.post(f"{CONV}{project.pk}/messages/", {"body": "Hi"}).status_code == 201
    assert outsider.post(f"{CONV}{project.pk}/leave/").status_code == 204
    assert outsider.post(f"{CONV}{general().pk}/leave/").status_code == 400  # everyone stays in General


def test_private_channel_and_dm_only_for_members(client_for, people):
    secret = channel("Pricing", people["manager"], private=True, members=[people["staff"]], department=people["manager"].department)
    services.send_message(secret, people["manager"], "Discount is 12%")
    dm, _ = services.get_or_create_dm(people["staff"], people["colleague"])
    services.send_message(dm, people["staff"], "Lunch?")

    outsider = client_for(people["outsider"])
    assert outsider.get(f"{CONV}{secret.pk}/").status_code == 404
    assert outsider.get(f"{CONV}{secret.pk}/messages/").status_code == 404
    assert outsider.post(f"{CONV}{secret.pk}/join/").status_code == 404
    assert outsider.get(f"{CONV}{dm.pk}/messages/").status_code == 404
    assert "Pricing" not in {c["name"] for c in outsider.get(CONV, {"scope": "browse"}).data}
    assert outsider.get("/api/v1/chat/messages/").status_code in (404, 405)

    # Admins see private channels to manage them, but read messages only as members; never other people's DMs.
    admin = client_for(people["admin"])
    assert "Pricing" in {c["name"] for c in admin.get(CONV, {"scope": "browse"}).data}
    assert admin.get(f"{CONV}{secret.pk}/messages/").status_code == 403
    assert admin.get(f"{CONV}{dm.pk}/messages/").status_code == 404

    staff = client_for(people["staff"])
    assert staff.get(f"{CONV}{secret.pk}/messages/").data["results"][0]["body"] == "Discount is 12%"
    assert staff.get(f"{CONV}{dm.pk}/messages/").status_code == 200


def test_who_can_create_and_manage_channels(client_for, people, departments):
    staff, manager, admin = (client_for(people[k]) for k in ("staff", "manager", "admin"))
    assert staff.post(CONV, {"name": "Mine"}).status_code == 400
    res = manager.post(CONV, {"name": "Sales Q4", "channel_type": "project", "is_private": True, "member_ids": [people["staff"].pk]}, format="json")
    assert res.status_code == 201, res.data
    assert res.data["department"] == departments["sales"].pk and res.data["member_count"] == 2
    assert manager.post(CONV, {"name": "Ops", "department": departments["ops"].pk}).status_code == 400
    assert manager.post(CONV, {"name": "All", "channel_type": "general"}).status_code == 400
    assert admin.post(CONV, {"name": "Ops plan", "department": departments["ops"].pk}).status_code == 201

    sales_q4 = res.data["id"]
    ops_plan = Conversation.objects.get(name="Ops plan").pk
    assert manager.patch(f"{CONV}{ops_plan}/", {"name": "Mine now"}).status_code == 403
    assert staff.patch(f"{CONV}{sales_q4}/", {"name": "Renamed"}).status_code == 403
    assert manager.patch(f"{CONV}{sales_q4}/", {"description": "Fourth quarter"}).status_code == 200
    assert manager.post(f"{CONV}{sales_q4}/members/", {"user_ids": [people["colleague"].pk]}, format="json").data["added"] == [people["colleague"].pk]
    assert manager.delete(f"{CONV}{sales_q4}/members/{people['colleague'].pk}/").status_code == 204
    assert staff.post(f"{CONV}{sales_q4}/members/", {"user_ids": [people["outsider"].pk]}, format="json").status_code == 403

    # Default channels: membership is automatic and they can't be archived.
    sales = dept_channel("Sales").pk
    assert manager.post(f"{CONV}{sales}/members/", {"user_ids": [people["outsider"].pk]}, format="json").status_code == 400
    assert manager.post(f"{CONV}{sales}/archive/").status_code == 400
    assert manager.patch(f"{CONV}{sales}/", {"is_private": False}).status_code == 400
    assert manager.patch(f"{CONV}{general().pk}/", {"name": "Everyone"}).status_code == 403

    assert manager.post(f"{CONV}{sales_q4}/archive/").data["archived"] is True
    assert manager.post(f"{CONV}{sales_q4}/messages/", {"body": "Still here?"}).status_code == 403
    assert "Sales Q4" not in mine(manager)


def test_channel_changes_are_audited_but_messages_are_not(client_for, people):
    manager = client_for(people["manager"])
    cid = manager.post(CONV, {"name": "Audit me"}).data["id"]
    manager.post(f"{CONV}{cid}/members/", {"user_ids": [people["staff"].pk]}, format="json")
    manager.delete(f"{CONV}{cid}/members/{people['staff'].pk}/")
    manager.patch(f"{CONV}{cid}/", {"is_private": True})
    manager.post(f"{CONV}{cid}/archive/")
    manager.post(f"{CONV}{general().pk}/messages/", {"body": "Not audited"})

    entries = AuditLog.objects.filter(object_id=str(cid), content_type__model="conversation").order_by("id")
    assert [e.action for e in entries] == ["create", "update", "update", "update", "update"]
    changes = [e.changes for e in entries]
    assert changes[1] == {"members_added": [None, "Staff"]} and changes[2] == {"members_removed": ["Staff", None]}
    assert changes[3] == {"is_private": [False, True]} and changes[4] == {"archived": [False, True]}
    assert not AuditLog.objects.filter(content_type__model="message").exists()


def test_anyone_can_start_a_dm_once(client_for, people):
    staff = client_for(people["staff"])
    first = staff.post(f"{CONV}direct/", {"user": people["outsider"].pk})
    assert first.status_code == 201 and first.data["other_person"]["full_name"] == "Omar Ops"
    again = client_for(people["outsider"]).post(f"{CONV}direct/", {"user": people["staff"].pk})
    assert again.status_code == 200 and again.data["id"] == first.data["id"]
    people["colleague"].is_active = False
    people["colleague"].save()
    assert staff.post(f"{CONV}direct/", {"user": people["colleague"].pk}).status_code == 400
    assert staff.post(f"{CONV}{first.data['id']}/leave/").status_code == 400


# ================================================================ history (cursor pagination)


def test_history_is_newest_first_with_stable_cursor(client_for, people):
    c = general()
    for i in range(70):
        services.send_message(c, people["manager"], f"Message {i}")
    client = client_for(people["staff"])
    page = client.get(f"{CONV}{c.pk}/messages/").data
    assert [m["body"] for m in page["results"]][:2] == ["Message 69", "Message 68"] and len(page["results"]) == 30
    services.send_message(c, people["manager"], "Arrived while reading")  # must not shift older pages
    seen = [m["body"] for m in page["results"]]
    while page["next"]:
        page = client.get(page["next"]).data
        seen += [m["body"] for m in page["results"]]
    assert seen == [f"Message {i}" for i in range(69, -1, -1)]


def test_history_query_count_does_not_grow(client_for, people):
    c = general()
    client = client_for(people["staff"])

    def count():
        with CaptureQueriesContext(connection) as ctx:
            client.get(f"{CONV}{c.pk}/messages/")
        return len(ctx)

    services.send_message(c, people["manager"], "One")
    small = count()
    for i in range(40):
        services.send_message(c, [people["manager"], people["colleague"], people["outsider"]][i % 3], f"More {i}")
    assert count() == small


# ================================================================ edit and delete


def test_edit_own_within_fifteen_minutes(client_for, people):
    m = services.send_message(general(), people["staff"], "Helo")
    staff, other = client_for(people["staff"]), client_for(people["colleague"])
    assert other.patch(f"{MSG}{m.pk}/", {"body": "Hacked"}).status_code == 403
    res = staff.patch(f"{MSG}{m.pk}/", {"body": "Hello"})
    assert res.status_code == 200 and res.data["body"] == "Hello" and res.data["edited_at"]
    assert staff.patch(f"{MSG}{m.pk}/", {"body": "   "}).status_code == 400
    later = timezone.now() + timedelta(minutes=16)
    with mock.patch("django.utils.timezone.now", return_value=later):
        assert staff.patch(f"{MSG}{m.pk}/", {"body": "Too late"}).status_code == 403


def test_delete_own_shows_message_deleted(client_for, people):
    m = services.send_message(general(), people["staff"], "Oops, wrong channel")
    staff = client_for(people["staff"])
    assert client_for(people["colleague"]).delete(f"{MSG}{m.pk}/").status_code == 403
    assert staff.delete(f"{MSG}{m.pk}/").status_code == 204
    shown = staff.get(f"{CONV}{general().pk}/messages/").data["results"][0]
    assert shown["deleted"] is True and shown["body"] == "" and shown["id"] == m.pk
    assert Message.objects.get(pk=m.pk).body == ""  # the text is gone, not just hidden
    assert staff.patch(f"{MSG}{m.pk}/", {"body": "Back"}).status_code == 400
    assert mine(client_for(people["colleague"]))["General"]["last_message"]["deleted"] is True


# ================================================================ read state and unread counts


def test_unread_counts_and_mark_read(client_for, people):
    s, mgr, col = people["staff"], people["manager"], people["colleague"]
    sales = dept_channel("Sales")
    for text in ("One", "Two", "Three"):
        services.send_message(sales, mgr, text)
    services.send_message(sales, s, "My own reply")  # your own messages are never unread...
    services.send_message(general(), col, "Hello all")
    gone = services.send_message(general(), col, "Typo")
    services.delete_message(gone)  # ...and deleted ones aren't either

    staff = client_for(s)
    convs = mine(staff)
    assert convs["Sales"]["unread_count"] == 0  # sending moves your read position past earlier messages
    assert convs["General"]["unread_count"] == 1
    assert list(convs)[0] == "General"  # most recent activity first
    assert convs["General"]["last_message"]["author"]["full_name"] == "Sara Colleague"
    services.send_message(sales, mgr, "Four")
    assert staff.get(f"{CONV}unread/").data == {"count": 2}

    first = Message.objects.filter(conversation=sales, body="Four").get()
    assert staff.post(f"{CONV}{sales.pk}/read/", {"message": first.pk - 1}).data == {"unread": 1}
    assert staff.post(f"{CONV}{sales.pk}/read/").data == {"unread": 0}
    assert staff.post(f"{CONV}{sales.pk}/read/", {"message": 1}).data == {"unread": 0}  # never moves back
    assert staff.get(f"{CONV}unread/").data == {"count": 1}


def test_conversation_list_query_count_does_not_grow(client_for, people, make_user):
    client = client_for(people["staff"])

    def count():
        with CaptureQueriesContext(connection) as ctx:
            client.get(CONV)
        return len(ctx)

    first, _ = services.get_or_create_dm(people["staff"], people["colleague"])
    services.send_message(first, people["colleague"], "Hi")  # so every query runs from the start
    small = count()
    for i in range(6):
        other = make_user(f"p{i}@test.com")
        dm, _ = services.get_or_create_dm(people["staff"], other)
        services.send_message(dm, other, "Hi")
        services.send_message(channel(f"Project {i}", people["manager"], members=[people["staff"]]), other, "Update")
    assert count() == small


# ================================================================ live delivery


def test_events_go_only_to_members(people, django_capture_on_commit_callbacks):
    secret = channel("Pricing", people["manager"], private=True, members=[people["staff"]])
    with mock.patch("apps.chat.services.push") as push, django_capture_on_commit_callbacks(execute=True):
        m = services.send_message(secret, people["manager"], "Members only")
        services.edit_message(m, "Members only!")
    recipients = [c.args[0] for c in push.call_args_list]
    assert sorted(set(recipients)) == sorted([people["manager"].pk, people["staff"].pk])
    events = {(c.args[0], c.args[1]["data"]["event"], c.args[1]["data"]["unread"]) for c in push.call_args_list}
    assert (people["staff"].pk, "message.new", 1) in events and (people["manager"].pk, "message.new", 0) in events
    assert (people["staff"].pk, "message.updated", 1) in events


@pytest.mark.django_db(transaction=True)
async def test_websocket_delivers_messages_to_members_only(make_user):
    sender = await database_sync_to_async(make_user)("sender@test.com")
    member = await database_sync_to_async(make_user)("member@test.com")
    outsider = await database_sync_to_async(make_user)("outsider@test.com", department="ops")
    sales = await database_sync_to_async(dept_channel)("Sales")

    async def connect(user):
        ws = WebsocketCommunicator(application, f"/ws/notifications/?ticket={issue_ticket(user)}", headers=[(b"origin", b"http://localhost")])
        assert (await ws.connect())[0]
        await ws.receive_json_from()  # notification unread count on connect
        return ws

    member_ws, outsider_ws = await connect(member), await connect(outsider)
    await database_sync_to_async(services.send_message)(sales, sender, "Sales only")
    event = await member_ws.receive_json_from(timeout=2)
    while event.get("event") == "presence":  # colleagues coming online are announced too
        event = await member_ws.receive_json_from(timeout=2)
    assert event["event"] == "message.new" and event["message"]["body"] == "Sales only" and event["unread"] == 1
    while not await outsider_ws.receive_nothing(timeout=0.3):
        assert (await outsider_ws.receive_json_from())["event"] != "message.new"

    # Read on one device: the user's other open sessions hear about it.
    await database_sync_to_async(services.mark_read)(sales, member)
    event = await member_ws.receive_json_from(timeout=2)
    while event.get("event") != "read":  # skips presence changes and the in-app notification
        event = await member_ws.receive_json_from(timeout=2)
    await member_ws.disconnect()
    await outsider_ws.disconnect()


# ================================================================ rate limit


def test_sending_is_rate_limited(client_for, people):
    client = client_for(people["staff"])
    url = f"{CONV}{general().pk}/messages/"
    codes = [client.post(url, {"body": f"Spam {i}"}).status_code for i in range(31)]
    assert codes[:30] == [201] * 30 and codes[30] == 429
    assert client.get(url).status_code == 200  # reading is not limited
    assert client_for(people["colleague"]).post(url, {"body": "Others can still talk"}).status_code == 201
    assert Membership.objects.filter(conversation=general()).count() == 5
