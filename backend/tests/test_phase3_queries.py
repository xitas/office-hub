"""Phase 3 review: the number of database queries per request must not grow with the data.

Each test measures an endpoint, adds several times more rows of every kind the response shows
(people, departments, files, reactions, mentions, reads, follow-ups…), and measures again.
"""
import io
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.announcements import services as announcement_services
from apps.announcements.models import Announcement, AnnouncementRead
from apps.chat import services as chat
from apps.chat.models import Conversation
from apps.contacts.models import Company, Contact
from apps.message_templates.models import MessageTemplate

pytestmark = pytest.mark.django_db


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {"admin": admin, "manager": manager, "staff": staff, "colleague": make_user("colleague@test.com", full_name="Sara Colleague")}


def queries(client, url, params=None) -> int:
    client.get(url, params)  # warm per-process caches (organization settings, content types)
    with CaptureQueriesContext(connection) as ctx:
        res = client.get(url, params)
    assert res.status_code == 200, (url, res.status_code)
    return len(ctx)


def tag(user):
    return f"@[{user.full_name}](user:{user.pk})"


def general():
    chat.ensure_default_channels()
    return Conversation.objects.get(is_default=True, channel_type=Conversation.ChannelType.GENERAL)


def _png(name="photo.png"):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(buf, "PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


# ================================================================ chat


def test_chat_mentions_and_search_do_not_grow(client_for, people, make_user):
    staff = client_for(people["staff"])
    channel = general()

    def add(n, offset=0):
        for i in range(n):
            author = make_user(f"writer{offset + i}@test.com")
            chat.sync_default_memberships(author)
            message = chat.send_message(channel, author, f"Quotation {i} for {tag(people['staff'])}", files=[_png()] if i % 2 else ())
            chat.toggle_reaction(message, people["colleague"], "👍")

    add(2)
    before = {
        "mentions": queries(staff, "/api/v1/chat/mentions/"),
        "search": queries(staff, "/api/v1/chat/search/", {"q": "quotation"}),
        "global": queries(staff, "/api/v1/search/", {"q": "quotation"}),
    }
    add(8, offset=10)
    after = {
        "mentions": queries(staff, "/api/v1/chat/mentions/"),
        "search": queries(staff, "/api/v1/chat/search/", {"q": "quotation"}),
        "global": queries(staff, "/api/v1/search/", {"q": "quotation"}),
    }
    assert after == before


# ================================================================ communication log


def test_communication_log_and_timeline_do_not_grow(client_for, people):
    client = client_for(people["staff"])
    company = Company.objects.create(name="Acme", assigned_to=people["staff"])

    def add(n):
        for i in range(n):
            contact = Contact.objects.create(first_name=f"C{i}", last_name="X", company=company, assigned_to=people["staff"])
            for kind, details in (("call", {"direction": "out", "outcome": "connected"}), ("email", {"direction": "out", "subject": "Hi"}), ("whatsapp", {"direction": "in"})):
                res = client.post("/api/v1/timeline/", {
                    "kind": kind, "contact": contact.pk, "summary": f"{kind} {i}", "details": details,
                    "follow_up_on": str((timezone.localdate() + timedelta(days=2))) if kind == "call" else None,
                }, format="json")
                assert res.status_code == 201, res.data
        return contact

    contact = add(2)
    before = (queries(client, "/api/v1/timeline/log/"), queries(client, "/api/v1/timeline/", {"company": company.pk}),
              queries(client, "/api/v1/timeline/", {"contact": contact.pk}))
    add(6)
    after = (queries(client, "/api/v1/timeline/log/"), queries(client, "/api/v1/timeline/", {"company": company.pk}),
             queries(client, "/api/v1/timeline/", {"contact": contact.pk}))
    assert after == before


# ================================================================ templates


def test_template_list_does_not_grow(client_for, people, make_user, departments):
    client = client_for(people["manager"])

    def add(n, offset=0):
        for i in range(n):
            owner = make_user(f"owner{offset + i}@test.com", role="manager")
            MessageTemplate.objects.create(name=f"T{offset + i}", body="Hi {contact.first_name} {nope}", sharing="department",
                                           department=departments["sales"], created_by=owner)
            MessageTemplate.objects.create(name=f"E{offset + i}", body="Hello", sharing="everyone", created_by=people["admin"])

    add(2)
    before = queries(client, "/api/v1/templates/")
    add(8, offset=10)
    assert queries(client, "/api/v1/templates/") == before


# ================================================================ announcements and dashboard


def test_announcement_endpoints_do_not_grow(client_for, people, make_user, departments):
    admin, staff = client_for(people["admin"]), client_for(people["staff"])

    def add(n, offset=0):
        created = []
        for i in range(n):
            author = make_user(f"boss{offset + i}@test.com", role="manager")
            a = Announcement.objects.create(title=f"A{offset + i}", body="**Hi** [x](https://x.test)", created_by=author,
                                            audience="departments" if i % 2 else "everyone", pinned=i == 0)
            if i % 2:
                a.departments.set([departments["sales"], departments["ops"]])
            announcement_services.save_attachments(a, author, [_png(), _png("b.png")])
            reader = make_user(f"reader{offset + i}@test.com", department="ops" if i % 2 else "sales")
            AnnouncementRead.objects.create(announcement=a, user=reader)
            AnnouncementRead.objects.create(announcement=a, user=author)
            created.append(a)
        return created

    first = add(2)[0]
    urls = ["/api/v1/announcements/", f"/api/v1/announcements/{first.pk}/", f"/api/v1/announcements/{first.pk}/receipts/",
            "/api/v1/dashboard/"]
    before = [queries(admin, u) for u in urls] + [queries(staff, urls[0]), queries(staff, urls[3])]
    add(8, offset=10)
    for i in range(5):
        make_user(f"extra{i}@test.com")  # a bigger audience
    after = [queries(admin, u) for u in urls] + [queries(staff, urls[0]), queries(staff, urls[3])]
    assert after == before
