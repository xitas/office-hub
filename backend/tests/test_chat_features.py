"""Chat slice 2: replies, reactions, typing, presence, attachments, notifications and the delayed DM email."""
import io
from datetime import timedelta
from unittest import mock

import pytest
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from apps.chat import presence, services
from apps.chat.models import Conversation, Membership, Message, MessageAttachment
from apps.core.ws_auth import issue_ticket
from apps.notifications.models import Notification, NotificationPreference
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


def sales():
    return Conversation.objects.get(is_default=True, channel_type="department", department__name="Sales")


def png(name="photo.png", size=(40, 30)):
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buf, "PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


def history(client, conversation):
    return client.get(f"{CONV}{conversation.pk}/messages/").data["results"]


# ================================================================ replies


def test_reply_quotes_the_original(client_for, people):
    original = services.send_message(sales(), people["manager"], "Can someone call Clifton Retail today?")
    staff = client_for(people["staff"])
    res = staff.post(f"{CONV}{sales().pk}/messages/", {"body": "I'll do it", "reply_to": original.pk})
    assert res.status_code == 201
    assert res.data["reply"] == {
        "id": original.pk, "author": services.person(people["manager"]), "body": "Can someone call Clifton Retail today?", "deleted": False,
    }
    elsewhere = services.send_message(general(), people["manager"], "Other channel")
    assert staff.post(f"{CONV}{sales().pk}/messages/", {"body": "x", "reply_to": elsewhere.pk}).status_code == 400

    services.delete_message(original)
    reply = history(staff, sales())[0]
    assert reply["reply"]["deleted"] is True and reply["reply"]["body"] == ""


# ================================================================ reactions


def test_reactions_toggle_with_counts_and_people(client_for, people):
    m = services.send_message(sales(), people["manager"], "Deal closed!")
    staff, colleague = client_for(people["staff"]), client_for(people["colleague"])
    assert staff.post(f"{MSG}{m.pk}/react/", {"emoji": "🎉"}).data["reacted"] is True
    res = colleague.post(f"{MSG}{m.pk}/react/", {"emoji": "🎉"})
    assert res.data["message"]["reactions"] == [{"emoji": "🎉", "count": 2, "users": [
        {"id": people["staff"].pk, "full_name": "Staff"}, {"id": people["colleague"].pk, "full_name": "Sara Colleague"},
    ]}]
    assert staff.post(f"{MSG}{m.pk}/react/", {"emoji": "🎉"}).data["reacted"] is False  # second click removes it
    assert history(staff, sales())[0]["reactions"][0]["count"] == 1
    assert staff.post(f"{MSG}{m.pk}/react/", {"emoji": "🍕"}).status_code == 400  # only the fixed set


def test_reactions_need_membership(client_for, people):
    m = services.send_message(general(), people["manager"], "Hello")
    services.remove_members(general(), [people["outsider"].pk])
    assert client_for(people["outsider"]).post(f"{MSG}{m.pk}/react/", {"emoji": "👍"}).status_code == 403  # can read, can't react
    secret = services.send_message(sales(), people["manager"], "Sales only")
    assert client_for(people["outsider"]).post(f"{MSG}{secret.pk}/react/", {"emoji": "👍"}).status_code == 404
    services.delete_message(m)
    assert client_for(people["staff"]).post(f"{MSG}{m.pk}/react/", {"emoji": "👍"}).status_code == 400


def test_reaction_updates_reach_members_only(people, django_capture_on_commit_callbacks):
    m = services.send_message(sales(), people["manager"], "Members only")
    with mock.patch("apps.chat.services.push") as push, django_capture_on_commit_callbacks(execute=True):
        services.toggle_reaction(m, people["staff"], "👍")
    recipients = {c.args[0] for c in push.call_args_list}
    assert recipients == {people["manager"].pk, people["staff"].pk, people["colleague"].pk}
    event = push.call_args_list[0].args[1]["data"]
    assert event["event"] == "message.updated" and event["message"]["reactions"][0]["emoji"] == "👍"


# ================================================================ typing and presence over the WebSocket


async def _connect(user):
    ws = WebsocketCommunicator(application, f"/ws/notifications/?ticket={issue_ticket(user)}", headers=[(b"origin", b"http://localhost")])
    assert (await ws.connect())[0]
    assert (await ws.receive_json_from())["type"] == "unread_count"
    return ws


async def _none(ws, event, timeout=0.4):
    """No chat event of this kind arrives (receive_nothing keeps the connection usable)."""
    while not await ws.receive_nothing(timeout=timeout):
        assert (await ws.receive_json_from()).get("event") != event


async def _next(ws, event, timeout=2):
    """The next chat event of this kind (others, e.g. presence changes, are skipped)."""
    while True:
        data = await ws.receive_json_from(timeout=timeout)
        if data.get("event") == event:
            return data


@pytest.mark.django_db(transaction=True)
async def test_typing_goes_to_other_members_only_and_is_throttled(make_user):
    writer = await database_sync_to_async(make_user)("writer@test.com", full_name="Sana Writer")
    member = await database_sync_to_async(make_user)("member@test.com")
    outsider = await database_sync_to_async(make_user)("outsider@test.com", department="ops")
    channel = await database_sync_to_async(sales)()

    member_ws, outsider_ws, writer_ws = await _connect(member), await _connect(outsider), await _connect(writer)
    await writer_ws.send_json_to({"type": "chat.typing", "conversation": channel.pk})
    await writer_ws.send_json_to({"type": "chat.typing", "conversation": channel.pk})  # within 3 s: dropped
    event = await _next(member_ws, "typing")
    assert event == {"type": "chat", "event": "typing", "conversation": channel.pk, "user": {"id": writer.pk, "full_name": "Sana Writer"}}
    await _none(member_ws, "typing")

    # Typing into a conversation you're not in reaches nobody.
    await outsider_ws.send_json_to({"type": "chat.typing", "conversation": channel.pk})
    await _none(member_ws, "typing")
    await _none(outsider_ws, "typing")
    for ws in (member_ws, outsider_ws, writer_ws):
        await ws.disconnect()


@pytest.mark.django_db(transaction=True)
async def test_presence_online_and_offline_for_colleagues_only(make_user, client_for):
    watcher = await database_sync_to_async(make_user)("watcher@test.com")
    loner = await database_sync_to_async(make_user)("loner@test.com", department=None)
    # Someone who shares no conversation with the others (removed from General).
    await database_sync_to_async(lambda: Membership.objects.filter(user=loner).delete())()
    arriving = await database_sync_to_async(make_user)("arriving@test.com")

    watcher_ws, loner_ws = await _connect(watcher), await _connect(loner)
    arriving_ws = await _connect(arriving)
    assert await _next(watcher_ws, "presence") == {"type": "chat", "event": "presence", "user": arriving.pk, "online": True}
    await _none(loner_ws, "presence")

    online = await database_sync_to_async(lambda: client_for(watcher).get(f"{CONV}presence/").data["online"])()
    assert arriving.pk in online and loner.pk not in online  # the loner shares nothing with the watcher

    await arriving_ws.disconnect()
    assert await _next(watcher_ws, "presence") == {"type": "chat", "event": "presence", "user": arriving.pk, "online": False}
    await watcher_ws.disconnect()
    await loner_ws.disconnect()


def test_presence_expires_without_pings(people):
    uid = people["staff"].pk
    assert presence.touch(uid, "tab-1") == (False, True)
    assert presence.touch(uid, "tab-2") == (True, True)
    assert presence.touch(uid, "tab-1", remove=True) == (True, True)  # still online in another tab
    later = presence.time.time() + presence.CONNECTION_TTL + 1
    with mock.patch("apps.chat.presence.time.time", return_value=later):
        assert presence.is_online(uid) is False  # a tab that vanished without saying goodbye
        assert presence.online_ids([uid]) == set()


# ================================================================ attachments


def test_image_attachment_with_thumbnail_and_private_download(client_for, people):
    staff = client_for(people["staff"])
    res = staff.post(f"{CONV}{sales().pk}/messages/", {"body": "", "files": [png()]}, format="multipart")
    assert res.status_code == 201, res.data
    a = res.data["attachments"][0]
    assert a["kind"] == "image" and a["original_name"] == "photo.png" and a["thumbnail_url"]
    assert staff.get("/api/v1" + a["download_url"]).status_code == 200
    assert staff.get("/api/v1" + a["thumbnail_url"])["Content-Type"] == "image/webp"
    assert client_for(people["colleague"]).get("/api/v1" + a["download_url"]).status_code == 200  # a member
    assert client_for(people["outsider"]).get("/api/v1" + a["download_url"]).status_code == 404  # not in Sales
    assert client_for(people["admin"]).get("/api/v1" + a["download_url"]).status_code == 404  # admins aren't members either
    preview = {c["name"]: c for c in staff.get(CONV).data}["Sales"]["last_message"]["body"]
    assert preview == "📎 photo.png"


def test_attachment_rules_match_task_files(client_for, people):
    staff = client_for(people["staff"])
    url = f"{CONV}{sales().pk}/messages/"
    fake = SimpleUploadedFile("invoice.pdf", b"MZ\x90\x00 this is a program", content_type="application/pdf")
    res = staff.post(url, {"body": "See attached", "files": [fake]}, format="multipart")
    assert res.status_code == 400 and "not really a PDF" in str(res.data)
    svg = SimpleUploadedFile("logo.svg", b"<svg onload='alert(1)'/>", content_type="image/svg+xml")
    assert staff.post(url, {"files": [svg]}, format="multipart").status_code == 400
    assert staff.post(url, {"files": [png(f"p{i}.png") for i in range(6)]}, format="multipart").status_code == 400
    assert not Message.objects.filter(conversation=sales()).exists()  # nothing half-sent
    assert staff.post(url, {"body": ""}, format="multipart").status_code == 400  # needs text or a file


def test_deleting_a_message_removes_its_files(client_for, people, settings):
    staff = client_for(people["staff"])
    res = staff.post(f"{CONV}{sales().pk}/messages/", {"body": "Oops", "files": [png()]}, format="multipart")
    attachment = MessageAttachment.objects.get(pk=res.data["attachments"][0]["id"])
    path = attachment.file.path
    assert staff.delete(f"{MSG}{res.data['id']}/").status_code == 204
    assert not MessageAttachment.objects.exists()
    import os

    assert not os.path.exists(path)
    assert staff.get("/api/v1" + res.data["attachments"][0]["download_url"]).status_code == 404


# ================================================================ notifications


def _send(conversation, author, text, capture):
    with capture(execute=True):
        return services.send_message(conversation, author, text)


def test_dm_and_channel_notifications_only_when_not_viewing(people, django_capture_on_commit_callbacks):
    s, c = people["staff"], people["colleague"]
    dm, _ = services.get_or_create_dm(s, c)
    _send(dm, s, "Are you coming to the meeting?", django_capture_on_commit_callbacks)
    n = Notification.objects.get(recipient=c)
    assert (n.type, n.link, n.message_key) == ("direct_message", f"/chat/{dm.pk}", "chat_direct")
    assert n.title == "Message from Staff" and n.body == "Are you coming to the meeting?"
    assert not Notification.objects.filter(recipient=s).exists()  # never for your own message
    assert mail.outbox == []  # DMs are emailed later, only if still unread

    presence.touch(c.pk, "tab", viewing=dm.pk)
    _send(dm, s, "Seen?", django_capture_on_commit_callbacks)
    assert Notification.objects.filter(recipient=c).count() == 1  # looking at it: no notification

    _send(sales(), people["manager"], "Team meeting at 3", django_capture_on_commit_callbacks)
    channel_note = Notification.objects.get(recipient=s, type="channel_message")
    assert channel_note.title == "New message in #Sales" and channel_note.body == "Manager: Team meeting at 3"
    assert not Notification.objects.filter(recipient=people["outsider"]).exists()  # not a member


def test_muted_conversation_sends_nothing_and_leaves_the_badge(client_for, people, django_capture_on_commit_callbacks):
    staff = client_for(people["staff"])
    assert staff.post(f"{CONV}{sales().pk}/mute/", {"muted": True}).data["muted"] is True
    _send(sales(), people["manager"], "Busy channel", django_capture_on_commit_callbacks)
    assert not Notification.objects.filter(recipient=people["staff"]).exists()
    assert staff.get(f"{CONV}unread/").data == {"count": 0}  # muted doesn't count in the badge...
    assert {c["name"]: c for c in staff.get(CONV).data}["Sales"]["unread_count"] == 1  # ...but the list still shows it
    assert client_for(people["outsider"]).post(f"{CONV}{sales().pk}/mute/", {"muted": True}).status_code == 404


def test_reading_clears_chat_notifications(client_for, people, django_capture_on_commit_callbacks):
    dm, _ = services.get_or_create_dm(people["staff"], people["colleague"])
    _send(dm, people["staff"], "Hi", django_capture_on_commit_callbacks)
    client_for(people["colleague"]).post(f"{CONV}{dm.pk}/read/")
    assert not Notification.objects.filter(recipient=people["colleague"], is_read=False).exists()


# ================================================================ delayed DM email


def _aged(message, minutes):
    Message.objects.filter(pk=message.pk).update(created_at=timezone.now() - timedelta(minutes=minutes))


def test_unread_dm_email_after_thirty_minutes_never_twice(people, django_capture_on_commit_callbacks):
    s, c = people["staff"], people["colleague"]
    dm, _ = services.get_or_create_dm(s, c)
    first = services.send_message(dm, s, "Please send the quotation")
    _aged(first, 29)
    with django_capture_on_commit_callbacks(execute=True):
        assert services.send_unread_dm_emails() == 0  # not yet
    _aged(first, 31)
    with django_capture_on_commit_callbacks(execute=True):
        assert services.send_unread_dm_emails() == 1
        assert services.send_unread_dm_emails() == 0  # never twice
    assert mail.outbox[0].to == [c.email] and mail.outbox[0].subject == "Unread messages from Staff"
    assert "Please send the quotation" in mail.outbox[0].body and f"/chat/{dm.pk}" in mail.outbox[0].body

    second = services.send_message(dm, s, "Any update?")
    _aged(second, 40)
    with django_capture_on_commit_callbacks(execute=True):
        assert services.send_unread_dm_emails() == 1
    assert "Any update?" in mail.outbox[1].body and "Please send the quotation" not in mail.outbox[1].body


def test_no_dm_email_when_read_muted_disabled_or_stale(people, django_capture_on_commit_callbacks):
    s, c, o = people["staff"], people["colleague"], people["outsider"]
    read_dm, _ = services.get_or_create_dm(s, c)
    _aged(services.send_message(read_dm, s, "Read already"), 45)
    services.mark_read(read_dm, c)

    muted_dm, _ = services.get_or_create_dm(o, c)
    _aged(services.send_message(muted_dm, o, "Muted"), 45)
    services.set_muted(muted_dm, c, True)

    no_email_dm, _ = services.get_or_create_dm(c, s)
    assert no_email_dm == read_dm  # the same pair shares one conversation
    pref_dm, _ = services.get_or_create_dm(people["manager"], o)
    NotificationPreference.objects.create(user=o, type="direct_message", in_app=True, email=False)
    _aged(services.send_message(pref_dm, people["manager"], "Pref off"), 45)

    stale_dm, _ = services.get_or_create_dm(people["admin"], s)
    _aged(services.send_message(stale_dm, people["admin"], "From two days ago"), 60 * 48)

    channel_msg = services.send_message(sales(), people["manager"], "Channels never email")
    _aged(channel_msg, 45)
    with django_capture_on_commit_callbacks(execute=True):
        assert services.send_unread_dm_emails() == 0
    assert mail.outbox == []
