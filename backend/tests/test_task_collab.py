"""Checklist, comments, mentions, notifications, attachments and the task activity timeline."""
import io
import zipfile

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.core.models import AuditLog
from apps.notifications.models import Notification, NotificationPreference
from apps.tasks.models import ChecklistItem, Task, TaskAttachment, TaskComment

pytestmark = pytest.mark.django_db

TASKS = "/api/v1/tasks/"


@pytest.fixture
def private_media(settings):
    return settings.PRIVATE_MEDIA_ROOT  # a temp folder (see conftest)


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {
        "admin": admin,
        "manager": manager,  # Sales
        "staff": staff,  # Sales
        "colleague": make_user("colleague@test.com", full_name="Sara Colleague"),  # Sales
        "outsider": make_user("ops.person@test.com", department="ops", full_name="Omar Ops"),
        "ops_manager": make_user("ops.manager@test.com", role="manager", department="ops", full_name="Olga Ops"),
    }


@pytest.fixture
def task(people):
    t = Task.objects.create(title="Prepare proposal", created_by=people["manager"])
    t.assignees.set([people["staff"]])
    return t


def url(task, *parts):
    return f"{TASKS}{task.pk}/" + "".join(f"{p}/" for p in parts)


# ---------------------------------------------------------------- files for upload tests


def png(name="photo.png", size=(40, 30)):
    out = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(out, "PNG")
    return SimpleUploadedFile(name, out.getvalue(), content_type="image/png")


def docx(name="brief.docx"):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document/>")
    return SimpleUploadedFile(name, out.getvalue())


def plain_zip(name="photos.zip"):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("a.txt", "hello")
    return SimpleUploadedFile(name, out.getvalue())


def upload(client, task, *files):
    return client.post(url(task, "attachments"), {"files": list(files)}, format="multipart")


# ================================================================ checklist


def test_checklist_add_tick_and_progress(client_for, people, task):
    c = client_for(people["staff"])
    for text in ["Draft outline", "Get prices", "  Send   for review "]:
        assert c.post(url(task, "checklist"), {"text": text}, format="json").status_code == 201
    items = c.get(url(task, "checklist")).data
    assert [i["text"] for i in items] == ["Draft outline", "Get prices", "Send for review"]
    assert [i["position"] for i in items] == [1, 2, 3]
    res = c.patch(url(task, "checklist", items[0]["id"]), {"done": True}, format="json")
    assert res.data["done"] is True and res.data["done_by_name"] == people["staff"].full_name
    row = c.get(TASKS, {"mine": "true"}).data["results"][0]
    assert (row["checklist_done"], row["checklist_total"]) == (1, 3)
    assert c.get(url(task)).data["checklist_total"] == 3


def test_reorder(client_for, people, task):
    c = client_for(people["staff"])
    ids = [c.post(url(task, "checklist"), {"text": t}, format="json").data["id"] for t in "ABC"]
    res = c.post(url(task, "checklist", "reorder"), {"order": [ids[2], ids[0], ids[1]]}, format="json")
    assert [i["text"] for i in res.data] == ["C", "A", "B"]
    assert [i["text"] for i in c.get(url(task, "checklist")).data] == ["C", "A", "B"]
    # Every item exactly once.
    for bad in ([ids[0], ids[1]], [ids[0], ids[0], ids[1]], [*ids, 999]):
        assert c.post(url(task, "checklist", "reorder"), {"order": bad}, format="json").status_code == 400


def test_checklist_permissions(client_for, people, task):
    item = ChecklistItem.objects.create(task=task, text="Check numbers", position=1)
    outsider = client_for(people["outsider"])
    assert outsider.get(url(task, "checklist")).status_code == 404
    assert outsider.patch(url(task, "checklist", item.pk), {"done": True}, format="json").status_code == 404
    assert outsider.post(url(task, "checklist"), {"text": "x"}, format="json").status_code == 404
    manager = client_for(people["manager"])
    assert manager.patch(url(task, "checklist", item.pk), {"done": True}, format="json").status_code == 200


def test_ticking_needs_only_view_but_editing_needs_edit(client_for, people, task, monkeypatch):
    """With "tasks.edit" taken away from staff, they can still tick items but not change them."""
    from apps.core import permissions

    item = ChecklistItem.objects.create(task=task, text="Check numbers", position=1)
    matrix = {**permissions.PERMISSIONS["tasks"], "edit": permissions.MGMT}
    monkeypatch.setitem(permissions.PERMISSIONS, "tasks", matrix)
    c = client_for(people["staff"])
    assert c.patch(url(task, "checklist", item.pk), {"done": True}, format="json").status_code == 200
    assert c.patch(url(task, "checklist", item.pk), {"text": "Renamed"}, format="json").status_code == 403
    assert c.post(url(task, "checklist"), {"text": "New"}, format="json").status_code == 403
    assert c.delete(url(task, "checklist", item.pk)).status_code == 403
    assert c.post(url(task, "checklist", "reorder"), {"order": [item.pk]}, format="json").status_code == 403


def test_checklist_delete_is_audited(client_for, people, task):
    item = ChecklistItem.objects.create(task=task, text="Old step", position=1)
    assert client_for(people["staff"]).delete(url(task, "checklist", item.pk)).status_code == 204
    log = AuditLog.objects.get(action=AuditLog.Action.DELETE, object_id=str(item.pk))
    assert log.changes["text"] == "Old step" and log.changes["task"] == "Prepare proposal"


# ================================================================ comments and mentions


def test_comment_crud_rules(client_for, people, task):
    staff, colleague_c = client_for(people["staff"]), client_for(people["colleague"])
    res = staff.post(url(task, "comments"), {"body": "First draft attached tomorrow"}, format="json")
    assert res.status_code == 201 and res.data["can_edit"] is True and res.data["edited_at"] is None
    cid = res.data["id"]
    edited = staff.patch(url(task, "comments", cid), {"body": "First draft attached today"}, format="json")
    assert edited.data["edited_at"] is not None
    # The colleague can't see this task (not assigned, not a manager).
    assert colleague_c.patch(url(task, "comments", cid), {"body": "x"}, format="json").status_code == 404
    # The manager sees it, may delete but not edit someone else's comment.
    manager = client_for(people["manager"])
    assert manager.patch(url(task, "comments", cid), {"body": "x"}, format="json").status_code == 403
    assert manager.delete(url(task, "comments", cid)).status_code == 204
    assert AuditLog.objects.filter(action=AuditLog.Action.DELETE, object_id=str(cid)).exists()


def test_staff_cannot_delete_others_comments(client_for, people, task):
    comment = TaskComment.objects.create(task=task, author=people["manager"], body="Please hurry")
    res = client_for(people["staff"]).delete(url(task, "comments", comment.pk))
    assert res.status_code == 403 and TaskComment.objects.filter(pk=comment.pk).exists()


def test_comments_are_oldest_first_and_need_content(client_for, people, task):
    c = client_for(people["staff"])
    assert c.post(url(task, "comments"), {"body": "   "}, format="json").status_code == 400
    c.post(url(task, "comments"), {"body": "one"}, format="json")
    c.post(url(task, "comments"), {"body": "two"}, format="json")
    assert [x["body"] for x in c.get(url(task, "comments")).data] == ["one", "two"]


def mention(user):
    return f"@[{user.full_name}](user:{user.pk})"


def test_mentions_notify_people_who_can_see_the_task(client_for, people, task, django_capture_on_commit_callbacks):
    body = f"{mention(people['admin'])} and {mention(people['outsider'])} please check"
    with django_capture_on_commit_callbacks(execute=True):
        res = client_for(people["staff"]).post(url(task, "comments"), {"body": body}, format="json")
    comment = TaskComment.objects.get(pk=res.data["id"])
    assert list(comment.mentions.all()) == [people["admin"]]  # the Ops person can't see the task: ignored
    note = Notification.objects.get(recipient=people["admin"])
    assert note.type == "mention" and note.message_key == "task_mention" and note.link.startswith(f"/tasks/{task.pk}")
    assert not Notification.objects.filter(recipient=people["outsider"]).exists()


def test_new_comment_notifies_assignees_and_creator_but_not_the_author(client_for, people, task, django_capture_on_commit_callbacks):
    task.assignees.add(people["colleague"])
    with django_capture_on_commit_callbacks(execute=True):
        client_for(people["staff"]).post(url(task, "comments"), {"body": "Done my part"}, format="json")
    recipients = set(Notification.objects.filter(type="task_comment").values_list("recipient__email", flat=True))
    assert recipients == {"manager@test.com", "colleague@test.com"}  # creator + other assignee, not staff (author)
    title = Notification.objects.filter(recipient=people["manager"]).first()
    assert title.message_key == "task_comment"


def test_mentioned_follower_gets_one_notice_and_preferences_are_respected(client_for, people, task, django_capture_on_commit_callbacks):
    NotificationPreference.objects.create(user=people["manager"], type="mention", in_app=False, email=True)
    NotificationPreference.objects.create(user=people["admin"], type="mention", in_app=False, email=False)
    body = f"{mention(people['manager'])} {mention(people['admin'])}"
    with django_capture_on_commit_callbacks(execute=True):
        client_for(people["staff"]).post(url(task, "comments"), {"body": body}, format="json")
    # The creator was mentioned: mention notice only (by email, as chosen), no extra "new comment" notice.
    assert not Notification.objects.filter(recipient=people["manager"]).exists()
    assert [m.to for m in mail.outbox] == [[people["manager"].email]]
    assert not Notification.objects.filter(recipient=people["admin"]).exists()


def test_editing_a_comment_notifies_only_newly_mentioned(client_for, people, task, django_capture_on_commit_callbacks):
    c = client_for(people["staff"])
    with django_capture_on_commit_callbacks(execute=True):
        cid = c.post(url(task, "comments"), {"body": f"hi {mention(people['admin'])}"}, format="json").data["id"]
        c.patch(url(task, "comments", cid), {"body": f"hi {mention(people['admin'])} {mention(people['manager'])}"}, format="json")
    assert Notification.objects.filter(recipient=people["admin"], type="mention").count() == 1
    assert Notification.objects.filter(recipient=people["manager"], type="mention").count() == 1


def test_mention_suggestions_list_people_who_can_see_the_task(client_for, people, task):
    names = [p["full_name"] for p in client_for(people["staff"]).get(url(task, "people")).data]
    assert people["admin"].full_name in names and people["manager"].full_name in names and people["staff"].full_name in names
    assert "Omar Ops" not in names and "Olga Ops" not in names and "Sara Colleague" not in names
    assert [p["full_name"] for p in client_for(people["staff"]).get(url(task, "people"), {"q": "manag"}).data] == [people["manager"].full_name]


def test_notification_text_in_urdu(client_for, people, task, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        client_for(people["staff"]).post(url(task, "comments"), {"body": mention(people["admin"])}, format="json")
    res = client_for(people["admin"]).get("/api/v1/notifications/", HTTP_ACCEPT_LANGUAGE="ur")
    assert res.data["results"][0]["title"] == f"{people['staff'].full_name} نے آپ کا ذکر کیا"


# ================================================================ attachments


@pytest.mark.parametrize("make", [
    lambda: png(),
    lambda: SimpleUploadedFile("spec.pdf", b"%PDF-1.7\n%..."),
    lambda: docx(),
    lambda: SimpleUploadedFile("old.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100),
    lambda: SimpleUploadedFile("prices.csv", "name,price\nچائے,100\n".encode()),
    lambda: SimpleUploadedFile("notes.txt", b"plain text"),
    lambda: plain_zip(),
])
def test_allowed_files(client_for, people, task, make):
    res = upload(client_for(people["staff"]), task, make())
    assert res.status_code == 201, res.data
    a = TaskAttachment.objects.get()
    assert a.file.name.startswith("tasks/") and a.original_name not in a.file.name  # random stored name


@pytest.mark.parametrize("name,content,reason", [
    ("tool.exe", b"MZ\x90\x00", "not an allowed file type"),
    ("logo.svg", b"<svg onload=alert(1)>", "not an allowed file type"),
    ("page.html", b"<html>", "not an allowed file type"),
    ("fake.pdf", b"<html><script>alert(1)</script>", "not really a PDF"),
    ("fake.png", b"MZ\x90\x00 renamed program", "not really a PNG"),
    ("fake.jpg", None, "not really a JPG"),  # a real PNG named .jpg
    ("fake.docx", b"PK\x03\x04 not really a zip", "not really a DOCX"),
    ("fake.txt", b"\x00\x01\x02binary", "not really a TXT"),
    ("noext", b"hello", "not an allowed file type"),
])
def test_rejected_files(client_for, people, task, name, content, reason):
    f = png(name) if content is None else SimpleUploadedFile(name, content)
    res = upload(client_for(people["staff"]), task, f)
    assert res.status_code == 400 and reason in res.data["errors"]["files"][0]
    assert not TaskAttachment.objects.exists()


def test_office_zip_must_be_the_right_office_type(client_for, people, task):
    res = upload(client_for(people["staff"]), task, docx("sheet.xlsx"))  # a Word file named .xlsx
    assert res.status_code == 400


def test_size_limit(client_for, people, task):
    big = SimpleUploadedFile("big.txt", b"a" * (10 * 1024 * 1024 + 1))
    res = upload(client_for(people["staff"]), task, big)
    assert res.status_code == 400 and "10 MB" in res.data["errors"]["files"][0]
    ok = SimpleUploadedFile("max.txt", b"a" * (10 * 1024 * 1024))
    assert upload(client_for(people["staff"]), task, ok).status_code == 201


def test_one_bad_file_rejects_the_whole_upload(client_for, people, task):
    res = upload(client_for(people["staff"]), task, png(), SimpleUploadedFile("x.exe", b"MZ"))
    assert res.status_code == 400 and not TaskAttachment.objects.exists()


def test_image_thumbnail_and_downloads(client_for, people, task):
    res = upload(client_for(people["staff"]), task, png(size=(1200, 800)))
    a = res.data[0]
    assert a["kind"] == "image" and a["thumbnail_url"] and a["uploaded_by_name"] == people["staff"].full_name
    c = client_for(people["staff"])
    thumb = c.get(f"/api/v1{a['thumbnail_url']}")
    assert thumb.status_code == 200 and thumb["Content-Type"] == "image/webp"
    with Image.open(io.BytesIO(b"".join(thumb.streaming_content))) as img:
        assert max(img.size) <= 320
    dl = c.get(f"/api/v1{a['download_url']}")
    assert dl.status_code == 200 and dl["X-Content-Type-Options"] == "nosniff"
    assert 'attachment; filename="photo.png"' in dl["Content-Disposition"]
    inline = c.get(f"/api/v1{a['download_url']}", {"inline": "1"})
    assert "inline" in inline["Content-Disposition"]


@pytest.mark.parametrize("who,allowed", [
    ("staff", True),  # assignee
    ("manager", True),  # creator
    ("admin", True),
    ("colleague", False),  # same department, but not on the task
    ("outsider", False),
    ("ops_manager", False),
])
def test_download_permissions(client_for, people, task, who, allowed):
    a = upload(client_for(people["staff"]), task, SimpleUploadedFile("spec.pdf", b"%PDF-1.7")).data[0]
    res = client_for(people[who]).get(f"/api/v1{a['download_url']}")
    assert res.status_code == (200 if allowed else 404)


def test_files_are_not_in_the_public_media_folder(settings, client_for, people, task, private_media):
    upload(client_for(people["staff"]), task, SimpleUploadedFile("spec.pdf", b"%PDF-1.7"))
    stored = TaskAttachment.objects.get().file
    assert stored.path.startswith(str(private_media)) and not stored.path.startswith(str(settings.MEDIA_ROOT))
    assert client_for(people["staff"]).get(f"/media/{stored.name}").status_code == 404


@pytest.mark.parametrize("who,allowed", [("staff", True), ("manager", True), ("admin", True)])
def test_delete_rules(client_for, people, task, private_media, who, allowed):
    a = upload(client_for(people["staff"]), task, png()).data[0]
    stored = TaskAttachment.objects.get()
    paths = [stored.file.path, stored.thumbnail.path]
    res = client_for(people[who]).delete(f"/api/v1/task-attachments/{a['id']}/")
    assert res.status_code == 204
    assert not TaskAttachment.objects.exists()
    assert not any(__import__("os").path.exists(p) for p in paths)  # files removed from disk
    log = AuditLog.objects.get(action=AuditLog.Action.DELETE, object_id=str(a["id"]))
    assert log.changes["file"] == "photo.png"


def test_other_staff_cannot_delete_a_file(client_for, people, task):
    task.assignees.add(people["colleague"])
    a = upload(client_for(people["staff"]), task, png()).data[0]
    res = client_for(people["colleague"]).delete(f"/api/v1/task-attachments/{a['id']}/")
    assert res.status_code == 403 and TaskAttachment.objects.exists()
    assert client_for(people["colleague"]).get(url(task, "attachments")).data[0]["can_delete"] is False


def test_upload_is_audited(client_for, people, task):
    a = upload(client_for(people["staff"]), task, png()).data[0]
    log = AuditLog.objects.get(action=AuditLog.Action.CREATE, object_id=str(a["id"]))
    assert log.changes["file"] == "photo.png" and log.changes["task"] == "Prepare proposal"


def test_comment_with_attachments(client_for, people, task):
    c = client_for(people["staff"])
    res = c.post(url(task, "comments"), {"body": "", "files": [png(), docx()]}, format="multipart")
    assert res.status_code == 201, res.data
    assert {a["original_name"] for a in res.data["attachments"]} == {"photo.png", "brief.docx"}
    # Deleting the comment removes its files too.
    assert c.delete(url(task, "comments", res.data["id"])).status_code == 204
    assert not TaskAttachment.objects.exists()


def test_deleting_a_task_removes_its_files(client_for, people, task, private_media):
    upload(client_for(people["staff"]), task, png())
    path = TaskAttachment.objects.get().file.path
    assert client_for(people["manager"]).delete(url(task)).status_code == 204
    assert not __import__("os").path.exists(path)


# ================================================================ activity timeline


def test_activity_timeline(client_for, people):
    c = client_for(people["staff"])
    tid = c.post(TASKS, {"title": "Visit client", "due_date": "2026-11-01"}, format="json").data["id"]
    task = Task.objects.get(pk=tid)
    c.patch(url(task), {"status": "in_progress", "due_date": "2026-11-03", "assignees": [people["staff"].pk, people["colleague"].pk]}, format="json")
    item = c.post(url(task, "checklist"), {"text": "Book car"}, format="json").data
    c.patch(url(task, "checklist", item["id"]), {"done": True}, format="json")
    c.post(url(task, "comments"), {"body": "Car booked"}, format="json")
    upload(c, task, png())
    res = c.get(url(task, "activity"))
    kinds = [i["kind"] if i["type"] == "event" else "comment" for i in res.data["items"]]
    assert kinds == ["created", "status", "due", "assignees", "checklist_added", "checklist_done", "comment", "attachment_added"]
    status = res.data["items"][1]
    assert status["data"] == {"old": "todo", "new": "in_progress"} and status["actor_name"] == people["staff"].full_name
    assert res.data["items"][3]["data"] == {"added": ["Sara Colleague"], "removed": []}
    assert [a["original_name"] for a in res.data["attachments"]] == ["photo.png"]
    assert client_for(people["outsider"]).get(url(task, "activity")).status_code == 404
