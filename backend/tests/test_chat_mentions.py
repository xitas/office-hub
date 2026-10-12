"""Chat slice 3: @mentions (suggestions, @channel/@here, mute override, delayed email), the Mentions view,
message search, messages in global search, record link cards and the chat dashboard widgets."""
from datetime import date, timedelta

import pytest
from django.core import mail
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.chat import presence, services
from apps.chat.models import Conversation, Message, MessageMention
from apps.contacts.models import Company, Contact
from apps.notifications.models import Notification, NotificationPreference
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db

CONV = "/api/v1/chat/conversations/"


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


def tag(user):
    return f"@[{user.full_name}](user:{user.pk})"


def send(conversation, author, body, capture):
    with capture(execute=True):
        return services.send_message(conversation, author, body)


# ================================================================ suggestions and who can be mentioned


def test_suggestions_follow_who_can_read(client_for, people):
    staff = client_for(people["staff"])
    names = lambda res: [p["full_name"] for p in res.data["people"]]  # noqa: E731
    # Private department channel: its members only (never yourself).
    assert names(staff.get(f"{CONV}{sales().pk}/people/")) == ["Manager", "Sara Colleague"]
    # Public channel: anyone who can read it, members first; `q` narrows.
    project = Conversation.objects.create(name="Launch", channel_type="project")
    services.add_members(project, [people["staff"], people["colleague"]])
    found = names(staff.get(f"{CONV}{project.pk}/people/"))
    assert found[0] == "Sara Colleague" and "Omar Ops" in found
    assert names(staff.get(f"{CONV}{project.pk}/people/", {"q": "omar"})) == ["Omar Ops"]
    # Not readable: nothing to suggest.
    assert client_for(people["outsider"]).get(f"{CONV}{sales().pk}/people/").status_code == 404
    # @channel / @here are offered only to people who manage the channel.
    assert staff.get(f"{CONV}{sales().pk}/people/").data["can_broadcast"] is False
    assert client_for(people["manager"]).get(f"{CONV}{sales().pk}/people/").data["can_broadcast"] is True


def test_only_readers_are_mentioned(people, django_capture_on_commit_callbacks):
    m = send(sales(), people["manager"], f"{tag(people['staff'])} and {tag(people['outsider'])} please check", django_capture_on_commit_callbacks)
    assert set(MessageMention.objects.filter(message=m).values_list("user__email", flat=True)) == {"staff@test.com"}
    open_channel = Conversation.objects.create(name="Launch", channel_type="project")
    services.add_members(open_channel, [people["manager"]])
    m2 = send(open_channel, people["manager"], f"{tag(people['outsider'])} you can read this one", django_capture_on_commit_callbacks)
    assert MessageMention.objects.filter(message=m2, user=people["outsider"]).exists()  # public: anyone may be mentioned
    assert Notification.objects.filter(recipient=people["outsider"], type="chat_mention").exists()


# ================================================================ mute override and notifications


def test_mention_notifies_even_when_muted(people, django_capture_on_commit_callbacks):
    s, c = people["staff"], people["colleague"]
    services.set_muted(sales(), s, True)
    services.set_muted(sales(), c, True)
    send(sales(), people["manager"], f"{tag(s)} can you take the call?", django_capture_on_commit_callbacks)
    note = Notification.objects.get(recipient=s)
    assert note.type == "chat_mention" and note.title == "Manager mentioned you in #Sales"
    assert note.body == "@Staff can you take the call?"  # tokens read as names
    assert not Notification.objects.filter(recipient=c).exists()  # muted and not mentioned


def test_mentioned_person_gets_one_notification_not_two(people, django_capture_on_commit_callbacks):
    send(sales(), people["manager"], f"{tag(people['staff'])} hello", django_capture_on_commit_callbacks)
    assert list(Notification.objects.filter(recipient=people["staff"]).values_list("type", flat=True)) == ["chat_mention"]
    assert list(Notification.objects.filter(recipient=people["colleague"]).values_list("type", flat=True)) == ["channel_message"]


def test_viewing_suppresses_mention_notification(people, django_capture_on_commit_callbacks):
    presence.touch(people["staff"].pk, "tab", viewing=sales().pk)
    send(sales(), people["manager"], f"{tag(people['staff'])} see above", django_capture_on_commit_callbacks)
    assert not Notification.objects.filter(recipient=people["staff"]).exists()
    assert MessageMention.objects.filter(user=people["staff"]).exists()  # still listed under Mentions


def test_editing_in_a_mention_notifies_only_the_new_person(client_for, people, django_capture_on_commit_callbacks):
    m = send(sales(), people["manager"], f"{tag(people['staff'])} first", django_capture_on_commit_callbacks)
    Notification.objects.all().delete()
    with django_capture_on_commit_callbacks(execute=True):
        res = client_for(people["manager"]).patch(
            f"/api/v1/chat/messages/{m.pk}/", {"body": f"{tag(people['staff'])} and {tag(people['colleague'])} first"}
        )
    assert res.status_code == 200
    assert list(Notification.objects.values_list("recipient__email", flat=True)) == ["colleague@test.com"]


# ================================================================ @channel and @here


def test_channel_and_here_are_for_channel_managers(client_for, people, django_capture_on_commit_callbacks):
    url = f"{CONV}{sales().pk}/messages/"
    res = client_for(people["staff"]).post(url, {"body": "@channel meeting moved"})
    assert res.status_code == 400 and "body" in res.data["errors"]
    with django_capture_on_commit_callbacks(execute=True):
        assert client_for(people["manager"]).post(url, {"body": "@channel meeting moved to 4"}).status_code == 201
    mentioned = dict(MessageMention.objects.values_list("user__email", "kind"))
    assert mentioned == {"staff@test.com": "channel", "colleague@test.com": "channel"}
    assert Notification.objects.get(recipient=people["staff"]).title == "Manager notified everyone in #Sales"

    MessageMention.objects.all().delete()
    presence.touch(people["colleague"].pk, "tab-1")  # online now
    with django_capture_on_commit_callbacks(execute=True):
        client_for(people["manager"]).post(url, {"body": "@here quick question"})
    assert list(MessageMention.objects.values_list("user__email", flat=True)) == ["colleague@test.com"]

    # In a direct message the words are just text.
    dm, _ = services.get_or_create_dm(people["staff"], people["colleague"])
    assert client_for(people["staff"]).post(f"{CONV}{dm.pk}/messages/", {"body": "I'm @here"}).status_code == 201


def test_large_channel_broadcast_needs_confirmation(client_for, people, make_user):
    for i in range(10):
        make_user(f"extra{i}@test.com")
    url = f"{CONV}{general().pk}/messages/"
    admin = client_for(people["admin"])
    res = admin.post(url, {"body": "@channel office closes at 4 today"})
    assert res.status_code == 400 and res.data["errors"]["members"] == "15"
    assert not Message.objects.exists()
    assert admin.post(url, {"body": "@channel office closes at 4 today", "confirm_broadcast": True}).status_code == 201
    assert MessageMention.objects.count() == 14


# ================================================================ delayed email for mentions


def _aged(message, minutes):
    Message.objects.filter(pk=message.pk).update(created_at=timezone.now() - timedelta(minutes=minutes))


def test_unread_mention_is_emailed_once_even_if_muted(people, django_capture_on_commit_callbacks):
    s = people["staff"]
    services.set_muted(sales(), s, True)
    plain = services.send_message(sales(), people["manager"], "Just chatting")
    mention = services.send_message(sales(), people["manager"], f"{tag(s)} please send the quotation")
    _aged(plain, 45)
    _aged(mention, 40)
    with django_capture_on_commit_callbacks(execute=True):
        assert services.send_unread_dm_emails() == 1
        assert services.send_unread_dm_emails() == 0  # never twice
    email = mail.outbox[0]
    assert email.to == [s.email] and email.subject == "Manager mentioned you in #Sales"
    assert "@Staff please send the quotation" in email.body and "Just chatting" not in email.body
    assert "mention emails" in email.body
    assert mail.outbox[0].to == [s.email] and len(mail.outbox) == 1  # the colleague (not mentioned) gets nothing


def test_no_mention_email_when_read_or_turned_off(people, django_capture_on_commit_callbacks):
    s, c = people["staff"], people["colleague"]
    read = services.send_message(sales(), people["manager"], f"{tag(s)} read this")
    _aged(read, 45)
    services.mark_read(sales(), s)
    NotificationPreference.objects.create(user=c, type="chat_mention", in_app=True, email=False)
    _aged(services.send_message(sales(), people["manager"], f"{tag(c)} pref off"), 45)
    with django_capture_on_commit_callbacks(execute=True):
        assert services.send_unread_dm_emails() == 0


# ================================================================ Mentions view


def test_mentions_view_newest_first_and_scoped(client_for, people, django_capture_on_commit_callbacks):
    s = people["staff"]
    first = send(sales(), people["manager"], f"{tag(s)} first", django_capture_on_commit_callbacks)
    dm, _ = services.get_or_create_dm(people["colleague"], s)
    send(dm, people["colleague"], f"{tag(s)} second", django_capture_on_commit_callbacks)
    gone = send(general(), people["manager"], f"{tag(s)} deleted later", django_capture_on_commit_callbacks)
    services.delete_message(gone)
    staff = client_for(s)
    res = staff.get("/api/v1/chat/mentions/")
    assert [m["body"].split(") ")[-1] for m in res.data["results"]] == ["second", "first"]
    assert res.data["results"][0]["conversation_title"] == "Sara Colleague"
    assert res.data["results"][1]["conversation_title"] == "#Sales"
    assert res.data["unread"] == 2
    staff.post(f"{CONV}{sales().pk}/read/")
    assert staff.get("/api/v1/chat/mentions/").data["unread"] == 1

    # Moved to another department: the Sales mention is no longer readable, so no longer listed.
    s.department = people["outsider"].department
    s.save()
    assert first.pk not in [m["id"] for m in staff.get("/api/v1/chat/mentions/").data["results"]]


# ================================================================ message search


@pytest.fixture
def corpus(people):
    s, mgr, c, o = people["staff"], people["manager"], people["colleague"], people["outsider"]
    secret = Conversation.objects.create(name="Pricing", channel_type="project", is_private=True)
    services.add_members(secret, [mgr, c])
    left = Conversation.objects.create(name="Old project", channel_type="project", is_private=True)
    services.add_members(left, [s, mgr])
    archived = Conversation.objects.create(name="Archive me", channel_type="project")
    services.add_members(archived, [s])
    dm, _ = services.get_or_create_dm(s, c)
    other_dm, _ = services.get_or_create_dm(mgr, o)
    msgs = {
        "sales": services.send_message(sales(), mgr, "Quotation for Clifton Retail is ready"),
        "general": services.send_message(general(), o, "Office quotation for new chairs"),
        "dm": services.send_message(dm, c, "Did you send the quotation?"),
        "urdu": services.send_message(general(), c, "کوٹیشن تیار ہے، quotation attached"),
        "secret": services.send_message(secret, mgr, "Secret quotation discount 12%"),
        "left": services.send_message(left, mgr, "Old quotation draft"),
        "archived": services.send_message(archived, s, "Archived quotation note"),
        "other_dm": services.send_message(other_dm, mgr, "Private quotation chat"),
        "deleted": services.send_message(sales(), mgr, "Deleted quotation"),
    }
    services.delete_message(msgs["deleted"])
    services.remove_members(left, [s.pk])
    archived.archived_at = timezone.now()
    archived.save()
    return msgs


def test_search_only_finds_readable_messages(client_for, people, corpus):
    res = client_for(people["staff"]).get("/api/v1/chat/search/", {"q": "quot"})
    found = {m["id"] for m in res.data["results"]}
    assert found == {corpus[k].pk for k in ("sales", "general", "dm", "urdu")}
    assert res.data["terms"] == ["quot"]
    ordered = [m["id"] for m in res.data["results"]]
    assert ordered == sorted(ordered, reverse=True)  # newest first


def test_search_filters_and_words(client_for, people, corpus):
    staff = client_for(people["staff"])
    search = lambda **p: {m["id"] for m in staff.get("/api/v1/chat/search/", p).data["results"]}  # noqa: E731
    assert search(q="quotation clifton") == {corpus["sales"].pk}  # every word
    assert search(q="quotation", conversation=general().pk) == {corpus["general"].pk, corpus["urdu"].pk}
    assert search(q="quotation", author=people["colleague"].pk) == {corpus["dm"].pk, corpus["urdu"].pk}
    assert search(q="کوٹیشن") == {corpus["urdu"].pk}
    today = timezone.localdate().isoformat()
    assert len(search(q="quotation", date_from=today, date_to=today)) == 4
    assert search(q="quotation", date_to=(date.today() - timedelta(days=3)).isoformat()) == set()
    assert search(q="q") == set()  # too short
    # Searching a conversation you can't read finds nothing (no error that reveals it exists).
    secret = Conversation.objects.get(name="Pricing")
    assert search(q="quotation", conversation=secret.pk) == set()


def test_messages_in_global_search_are_scoped(client_for, people, corpus):
    hits = client_for(people["staff"]).get("/api/v1/search/", {"q": "quotation"}).data["results"].get("messages", [])
    ids = {h["id"] for h in hits}
    assert ids and ids <= {corpus[k].pk for k in ("sales", "general", "dm", "urdu")}
    hit = next(h for h in hits if h["id"] == corpus["dm"].pk)
    assert hit["title"] == "Sara Colleague · Direct message" and hit["url"] == f"/chat/{corpus['dm'].conversation_id}?message={corpus['dm'].pk}"
    assert not client_for(people["outsider"]).get("/api/v1/search/", {"q": "Clifton"}).data["results"].get("messages")


def test_message_in_context(client_for, people):
    for i in range(40):
        services.send_message(general(), people["manager"], f"Line {i}")
    pivot = Message.objects.get(body="Line 5")
    res = client_for(people["staff"]).get(f"{CONV}{general().pk}/messages/", {"around": pivot.pk})
    bodies = [m["body"] for m in res.data["results"]]
    assert bodies[0] == "Line 20" and bodies[-1] == "Line 0" and "Line 5" in bodies
    assert res.data["has_newer"] is True and res.data["has_older"] is False
    other = services.send_message(sales(), people["manager"], "Elsewhere")
    assert client_for(people["staff"]).get(f"{CONV}{general().pk}/messages/", {"around": other.pk}).status_code == 404


# ================================================================ record link cards


def test_record_cards_only_for_visible_records(client_for, people):
    s, o = people["staff"], people["outsider"]
    task = Task.objects.create(title="Send the quotation", created_by=s)
    task.assignees.set([s])
    company = Company.objects.create(name="Clifton Retail", industry="Retail", city="Karachi", assigned_to=s)
    contact = Contact.objects.create(first_name="Ali", last_name="Khan", company=company, assigned_to=s)
    url = "/api/v1/chat/record-card/"
    staff, outsider = client_for(s), client_for(o)
    card = staff.get(url, {"type": "task", "id": task.pk}).data
    assert card["title"] == "Send the quotation" and card["status_label"] == "To do" and card["url"] == f"/tasks/{task.pk}"
    assert staff.get(url, {"type": "contact", "id": contact.pk}).data["subtitle"] == "Clifton Retail"
    assert staff.get(url, {"type": "company", "id": company.pk}).data["subtitle"] == "Retail · Karachi"
    for kind, pk in (("task", task.pk), ("contact", contact.pk), ("company", company.pk)):
        assert outsider.get(url, {"type": kind, "id": pk}).status_code == 404  # can't see it: plain link
    assert staff.get(url, {"type": "user", "id": s.pk}).status_code == 404
    assert staff.get(url, {"type": "task", "id": "abc"}).status_code == 404


# ================================================================ dashboard


def test_dashboard_unread_messages_and_mentions(client_for, people, django_capture_on_commit_callbacks):
    s = people["staff"]
    dm, _ = services.get_or_create_dm(people["colleague"], s)
    send(dm, people["colleague"], "Lunch at 1?", django_capture_on_commit_callbacks)
    send(sales(), people["manager"], f"{tag(s)} please confirm", django_capture_on_commit_callbacks)
    send(general(), people["outsider"], "Muted chatter", django_capture_on_commit_callbacks)
    services.set_muted(general(), s, True)
    data = client_for(s).get("/api/v1/dashboard/").data
    items = {i["title"]: i for i in data["unread_messages"]}
    assert set(items) == {"Sara Colleague", "#Sales"}  # muted General left out
    assert items["#Sales"]["subtitle"] == "Manager: @Staff please confirm" and items["#Sales"]["badge"] == "1"
    assert items["Sara Colleague"]["url"] == f"/chat/{dm.pk}"
    assert data["chat_mentions"] == {"unread": 1}


def test_dashboard_chat_widgets_query_count_does_not_grow(client_for, people, make_user):
    s = people["staff"]
    client = client_for(s)

    def count():
        client.get("/api/v1/dashboard/")
        with CaptureQueriesContext(connection) as ctx:
            client.get("/api/v1/dashboard/")
        return len(ctx)

    dm, _ = services.get_or_create_dm(people["colleague"], s)
    services.send_message(dm, people["colleague"], f"Hi {tag(s)}")
    small = count()
    for i in range(4):
        other = make_user(f"p{i}@test.com")
        dm, _ = services.get_or_create_dm(other, s)
        services.send_message(dm, other, f"Hello {tag(s)}")
    assert count() == small
