"""Announcements: who posts to whom, who sees what, edit/delete with audit, read receipts,
notifications and emails, the dashboard widget, files, formatting and the archive."""
import io
from datetime import timedelta

import pytest
from django.core import mail
from PIL import Image

from apps.announcements import formatting
from apps.announcements.models import Announcement, AnnouncementRead
from apps.core.models import AuditLog
from apps.core.office_time import office_today
from apps.notifications.models import Notification, NotificationPreference

pytestmark = pytest.mark.django_db

URL = "/api/v1/announcements/"


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {
        "admin": admin, "manager": manager, "staff": staff,
        "colleague": make_user("colleague@test.com", full_name="Sara Colleague", language="ur"),
        "ops": make_user("ops.person@test.com", department="ops", full_name="Omar Ops"),
        "ops_manager": make_user("ops.manager@test.com", role="manager", department="ops", full_name="Olga Manager"),
        "nobody": make_user("floater@test.com", department=None, full_name="Fay Floater"),
    }


def post(client, **data):
    body = {"title": "Hello", "body": "Some **news**", "audience": "everyone", **data}
    return client.post(URL, body, format="json")


def titles(res):
    return sorted(a["title"] for a in res.data["results"])


# ================================================================ posting and visibility


def test_who_can_post_to_whom(client_for, people, departments):
    sales, ops = departments["sales"].pk, departments["ops"].pk
    staff, manager, admin = (client_for(people[k]) for k in ("staff", "manager", "admin"))
    assert post(staff, audience="departments", departments=[sales]).status_code == 403
    assert post(manager).status_code == 400  # managers can't post to everyone
    assert post(manager, audience="departments", departments=[ops]).status_code == 400
    assert post(manager, audience="departments", departments=[sales, ops]).status_code == 400
    assert post(manager, audience="departments", departments=[]).status_code == 400
    res = post(manager, audience="departments", departments=[sales])
    assert res.status_code == 201 and res.data["department_names"] == ["Sales"]
    assert post(admin).status_code == 201
    res = post(admin, audience="departments", departments=[sales, ops])
    assert res.status_code == 201 and sorted(res.data["department_names"]) == ["Operations", "Sales"]
    # Choosing "everyone" drops any departments sent along.
    assert post(admin, departments=[sales]).data["departments"] == []


def test_who_sees_which_announcement(client_for, people, departments, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        post(client_for(people["admin"]), title="All")
        post(client_for(people["manager"]), title="Sales only", audience="departments", departments=[departments["sales"].pk])
        post(client_for(people["ops_manager"]), title="Ops only", audience="departments", departments=[departments["ops"].pk])
    assert titles(client_for(people["staff"]).get(URL)) == ["All", "Sales only"]
    assert titles(client_for(people["ops"]).get(URL)) == ["All", "Ops only"]
    assert titles(client_for(people["nobody"]).get(URL)) == ["All"]
    assert titles(client_for(people["admin"]).get(URL)) == ["All", "Ops only", "Sales only"]
    ops_item = Announcement.objects.get(title="Ops only")
    assert client_for(people["staff"]).get(f"{URL}{ops_item.pk}/").status_code == 404
    assert client_for(people["staff"]).post(f"{URL}{ops_item.pk}/read/").status_code == 404


def test_edit_and_delete_by_author_or_admin_with_audit(client_for, people, departments):
    sales = departments["sales"].pk
    res = post(client_for(people["manager"]), title="Old", audience="departments", departments=[sales])
    url = f"{URL}{res.data['id']}/"
    assert client_for(people["staff"]).patch(url, {"title": "Hack"}, format="json").status_code == 403
    other_manager = client_for(people["ops_manager"])
    assert other_manager.patch(url, {"title": "Hack"}, format="json").status_code == 404  # can't even see it
    res = client_for(people["manager"]).patch(url, {"title": "New", "pinned": True}, format="json")
    assert res.status_code == 200 and res.data["title"] == "New" and res.data["pinned"]
    entry = AuditLog.objects.filter(action=AuditLog.Action.UPDATE, object_id=str(res.data["id"])).latest("timestamp")
    assert entry.changes["title"] == ["Old", "New"] and entry.changes["pinned"] == [False, True]
    assert client_for(people["admin"]).patch(url, {"body": "Admin fixed it"}, format="json").status_code == 200
    assert client_for(people["staff"]).delete(url).status_code == 403
    assert client_for(people["admin"]).delete(url).status_code == 204
    assert AuditLog.objects.filter(action=AuditLog.Action.DELETE, object_repr="New").exists()
    assert AuditLog.objects.filter(action=AuditLog.Action.CREATE, object_repr="Old").exists()


# ================================================================ read receipts


def test_read_receipts_are_scoped_to_the_audience(client_for, people, departments, django_capture_on_commit_callbacks):
    manager = client_for(people["manager"])
    with django_capture_on_commit_callbacks(execute=True):
        res = post(manager, audience="departments", departments=[departments["sales"].pk])
    pk = res.data["id"]
    # Audience: active Sales people except the author: staff and colleague.
    assert manager.get(f"{URL}{pk}/").data["receipts"] == {"read": 0, "total": 2}
    staff = client_for(people["staff"])
    assert staff.get(f"{URL}{pk}/").data["is_read"] is False
    assert staff.post(f"{URL}{pk}/read/").status_code == 200
    staff.post(f"{URL}{pk}/read/")  # only the first opening counts
    assert AnnouncementRead.objects.filter(announcement_id=pk, user=people["staff"]).count() == 1
    assert staff.get(f"{URL}{pk}/").data["is_read"] is True
    # Opening it clears the notification about it.
    assert not Notification.objects.filter(recipient=people["staff"], type="announcement", is_read=False).exists()
    assert Notification.objects.filter(recipient=people["colleague"], type="announcement", is_read=False).exists()

    assert staff.get(f"{URL}{pk}/").data["receipts"] is None
    assert staff.get(f"{URL}{pk}/receipts/").status_code == 403
    data = manager.get(f"{URL}{pk}/receipts/").data
    assert data["read_count"] == 1 and data["total"] == 2
    assert [p["full_name"] for p in data["read"]] == [people["staff"].full_name]
    assert [p["full_name"] for p in data["unread"]] == ["Sara Colleague"]
    assert client_for(people["admin"]).get(f"{URL}{pk}/receipts/").status_code == 200
    # Someone who moved to another department no longer counts.
    people["staff"].department = departments["ops"]
    people["staff"].save()
    assert manager.get(URL).data["results"][0]["receipts"] == {"read": 0, "total": 1}


# ================================================================ notifications and email


def test_new_announcement_notifies_and_emails_the_audience_once(client_for, people, departments, django_capture_on_commit_callbacks):
    NotificationPreference.objects.create(user=people["staff"], type="announcement", in_app=True, email=False)
    with django_capture_on_commit_callbacks(execute=True):
        res = post(
            client_for(people["manager"]), title="Team lunch", body="Lunch on **Friday**:\n- 1 pm\n- [Menu](https://example.com/menu)",
            audience="departments", departments=[departments["sales"].pk],
        )
    pk = res.data["id"]
    notified = set(Notification.objects.filter(type="announcement").values_list("recipient__email", flat=True))
    assert notified == {"staff@test.com", "colleague@test.com"}  # not the author, not other departments
    note = Notification.objects.get(recipient=people["staff"])
    assert note.link == f"/announcements/{pk}" and "Team lunch" in note.title
    # Email follows each person's settings: staff turned it off.
    assert [m.to for m in mail.outbox] == [["colleague@test.com"]]
    email = mail.outbox[0]
    assert "Team lunch" in email.subject
    assert "Friday" in email.body and "**" not in email.body and "Menu (https://example.com/menu)" in email.body
    assert f"/announcements/{pk}" in email.body
    # Urdu reader gets the email text in Urdu.
    assert "اعلان" in email.subject
    # Editing doesn't notify again.
    with django_capture_on_commit_callbacks(execute=True):
        client_for(people["manager"]).patch(f"{URL}{pk}/", {"title": "Team lunch (moved)"}, format="json")
    assert len(mail.outbox) == 1 and Notification.objects.filter(type="announcement").count() == 2


def test_dashboard_widget_shows_unread_current_announcements(client_for, people, django_capture_on_commit_callbacks):
    admin = client_for(people["admin"])
    with django_capture_on_commit_callbacks(execute=True):
        first = post(admin, title="First").data["id"]
        post(admin, title="Pinned", pinned=True)
        expired = post(admin, title="Expired").data["id"]
    Announcement.objects.filter(pk=expired).update(expires_on=office_today() - timedelta(days=1))
    staff = client_for(people["staff"])
    widget = staff.get("/api/v1/dashboard/").data["announcements"]
    assert widget["unread"] == 2 and [i["title"] for i in widget["items"]] == ["Pinned", "First"]
    staff.post(f"{URL}{first}/read/")
    assert staff.get("/api/v1/dashboard/").data["announcements"]["unread"] == 1
    assert client_for(people["admin"]).get("/api/v1/dashboard/").data["announcements"]["unread"] == 0  # own ones are read


# ================================================================ board, archive, files, formatting


def test_board_order_archive_and_expiry(client_for, people):
    admin = client_for(people["admin"])
    post(admin, title="Old")
    post(admin, title="Pinned", pinned=True)
    post(admin, title="New")
    gone = post(admin, title="Gone", expires_on=str(office_today())).data["id"]
    assert post(admin, title="Past", expires_on=str(office_today() - timedelta(days=1))).status_code == 400
    staff = client_for(people["staff"])
    assert [a["title"] for a in staff.get(URL).data["results"]] == ["Pinned", "Gone", "New", "Old"]  # expiry day still shows
    Announcement.objects.filter(pk=gone).update(expires_on=office_today() - timedelta(days=1))
    assert [a["title"] for a in staff.get(URL).data["results"]] == ["Pinned", "New", "Old"]
    archive = staff.get(URL, {"archive": "1"}).data["results"]
    assert [a["title"] for a in archive] == ["Gone"] and archive[0]["expired"] is True
    assert staff.get(f"{URL}{gone}/").status_code == 200  # archived ones still open


def _png():
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(buf, "PNG")
    buf.seek(0)
    buf.name = "photo.png"
    return buf


def test_files_follow_the_task_file_rules(client_for, people, departments):
    manager = client_for(people["manager"])
    fake = io.BytesIO(b"MZ not really a pdf")
    fake.name = "report.pdf"
    res = manager.post(URL, {"title": "T", "body": "B", "audience": "departments", "departments": [departments["sales"].pk], "files": [fake]})
    assert res.status_code == 400 and not Announcement.objects.exists()  # nothing saved when a file is refused
    res = manager.post(URL, {"title": "T", "body": "B", "audience": "departments", "departments": [departments["sales"].pk], "files": [_png(), _png()]})
    assert res.status_code == 201
    kept, dropped = res.data["attachments"]
    assert kept["kind"] == "image" and kept["thumbnail_url"]
    url = f"/api/v1{kept['download_url']}"
    assert client_for(people["staff"]).get(url).status_code == 200
    assert client_for(people["ops"]).get(url).status_code == 404  # not in the audience
    # (Removes the other file: Windows can't delete the one still open from the download.)
    res = manager.patch(f"{URL}{res.data['id']}/", {"remove_attachments": [dropped["id"]]}, format="json")
    assert res.status_code == 200 and [a["id"] for a in res.data["attachments"]] == [kept["id"]]
    assert client_for(people["staff"]).get(f"/api/v1{dropped['download_url']}").status_code == 404


def test_formatting_and_unsafe_links(client_for, people):
    body = "**Bold** start\n- one\n- [two](https://x.test/2)\n1. [https://y.test](https://y.test)"
    assert formatting.plain_text(body) == "Bold start\n- one\n- two (https://x.test/2)\n1. https://y.test"
    assert formatting.preview(body) == "Bold start one two (https://x.test/2) https://y.test"
    res = post(client_for(people["admin"]), body="Click [here](javascript:alert(1))")
    assert res.status_code == 400 and "body" in res.data["errors"]


def test_seed_creates_two_announcements(db):
    from django.core.management import call_command

    call_command("seed_demo", stdout=io.StringIO())
    assert Announcement.objects.count() == 2
    assert Announcement.objects.filter(pinned=True, audience="everyone").count() == 1
    assert not Notification.objects.filter(type="announcement").exists()  # seeding notifies nobody
