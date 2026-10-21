"""Images people upload are kept upright and without GPS, camera or other metadata, everywhere one is stored as the
original (task, chat and announcement attachments, expense receipts, resource photos): same format and size, JPEG
quality kept, PNG palettes and transparency, lossless WebP and animated GIFs as they were. A phone's MPO JPEG is
accepted. Other files are stored byte for byte. Thumbnails are upright. clean_stored_images cleans what was stored
before (dry run, counts, safe to run twice, skips other files and unreadable ones)."""
import io
from datetime import date

import pytest
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from PIL import Image, ImageDraw, PngImagePlugin

from apps.announcements.models import AnnouncementAttachment
from apps.bookings.models import Resource
from apps.chat.models import Conversation, MessageAttachment
from apps.core.photos import clean_image, needs_cleaning
from apps.expenses.models import ExpenseReceipt
from apps.tasks.models import Task, TaskAttachment

pytestmark = pytest.mark.django_db

GPS, MAKE, ORIENTATION = 0x8825, 0x010F, 0x0112


def exif(orientation=1):
    e = Image.Exif()
    e[ORIENTATION] = orientation
    e[MAKE] = "PhoneMaker"
    e.get_ifd(GPS).update({1: "N", 2: (31.0, 30.0, 42.0), 3: "E", 4: (74.0, 20.0, 46.0)})
    return e


def picture(size=(400, 200)):
    """Wide, with a red block at the top left: after "rotate 90° clockwise" (orientation 6) it's tall, red top right."""
    im = Image.new("RGB", size, "white")
    ImageDraw.Draw(im).rectangle([0, 0, 60, 40], fill=(255, 0, 0))
    return im


def phone_jpeg(name="IMG_0001.jpg"):
    buf = io.BytesIO()
    picture().save(buf, "JPEG", exif=exif(6), quality=88, xmp=b"<x:xmpmeta>where</x:xmpmeta>", comment=b"camera")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")


def upload(name, data, content_type="application/octet-stream"):
    return SimpleUploadedFile(name, data, content_type=content_type)


def read(field_file) -> bytes:
    with field_file.storage.open(field_file.name, "rb") as fh:
        return fh.read()


def opened(field_file):
    return Image.open(io.BytesIO(read(field_file)))


def is_clean_and_upright(im, size=(200, 400)):
    exif_left = im.getexif()
    return (not exif_left and not exif_left.get_ifd(GPS) and not im.info.get("xmp") and not im.info.get("comment")
            and im.size == size and not needs_cleaning(im))


def red_corner(im):
    return im.convert("RGB").getpixel((im.size[0] - 5, 5))  # top right once upright


# ================================================================ clean_image, format by format


def as_file(name, data):
    b = io.BytesIO(data)
    b.name = name
    return b


def test_jpeg_is_upright_without_metadata_and_keeps_its_quality():
    buf = io.BytesIO()
    picture().save(buf, "JPEG", exif=exif(6), quality=88, xmp=b"<x:xmpmeta>where</x:xmpmeta>", comment=b"camera")
    with Image.open(io.BytesIO(buf.getvalue())) as before:
        tables = before.quantization
    with Image.open(clean_image(as_file("a.jpg", buf.getvalue()), "jpg")) as im:
        assert im.format == "JPEG" and is_clean_and_upright(im)
        assert im.quantization == tables  # the same compression: quality kept
        assert red_corner(im)[0] > 200 and red_corner(im)[1] < 60


def test_phone_mpo_becomes_one_clean_jpeg():
    buf = io.BytesIO()
    picture().save(buf, "MPO", save_all=True, append_images=[picture((100, 50))], exif=exif(6))
    with Image.open(io.BytesIO(buf.getvalue())) as before:
        assert before.format == "MPO" and before.n_frames == 2
    with Image.open(clean_image(as_file("b.jpg", buf.getvalue()), "jpg")) as im:
        assert im.format == "JPEG" and getattr(im, "n_frames", 1) == 1 and is_clean_and_upright(im)


def test_png_keeps_palette_and_transparency_but_not_text_or_exif():
    p = Image.new("P", (40, 20), 0)
    p.putpalette([0, 0, 0, 255, 0, 0] + [0] * 762)
    meta = PngImagePlugin.PngInfo()
    meta.add_text("Comment", "secret location")
    buf = io.BytesIO()
    p.save(buf, "PNG", pnginfo=meta, transparency=0, exif=exif())
    with Image.open(clean_image(as_file("c.png", buf.getvalue()), "png")) as im:
        assert (im.format, im.mode, im.size, im.info.get("transparency")) == ("PNG", "P", (40, 20), 0)
        assert not im.text and not im.getexif()


@pytest.mark.parametrize("lossless", [True, False])
def test_webp_stays_lossless_or_lossy_and_is_upright(lossless):
    buf = io.BytesIO()
    picture().save(buf, "WEBP", exif=exif(6), lossless=lossless, quality=85)
    out = clean_image(as_file("d.webp", buf.getvalue()), "webp")
    data = out.read()
    assert (b"VP8L" in data[:64]) == lossless
    with Image.open(io.BytesIO(data)) as im:
        assert im.format == "WEBP" and is_clean_and_upright(im)


def test_animated_gif_keeps_frames_and_timing_but_not_comments():
    frames = []
    for i, colour in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255)]):
        im = Image.new("RGB", (30, 30), "white")
        ImageDraw.Draw(im).rectangle([i * 8, 5, i * 8 + 10, 20], fill=colour)
        frames.append(im)
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=[100, 200, 300], loop=0, comment=b"made at 31.5,74.3")
    with Image.open(clean_image(as_file("e.gif", buf.getvalue()), "gif")) as im:
        durations = []
        for k in range(im.n_frames):
            im.seek(k)
            durations.append(im.info.get("duration"))
            assert "comment" not in im.info
        assert (im.format, im.n_frames, durations, im.info.get("loop")) == ("GIF", 3, [100, 200, 300], 0)


# ================================================================ every place that stores uploads


@pytest.fixture
def task(staff):
    t = Task.objects.create(title="T", created_by=staff)
    t.assignees.set([staff])
    return t


def store(kind, client_for, admin, manager, staff, task, departments, files):
    """Upload through the API; returns the stored rows (newest first)."""
    if kind == "task":
        res = client_for(staff).post(f"/api/v1/tasks/{task.pk}/attachments/", {"files": files}, format="multipart")
        model = TaskAttachment
    elif kind == "chat":
        general = Conversation.objects.get(is_default=True, channel_type="general")
        res = client_for(staff).post(f"/api/v1/chat/conversations/{general.pk}/messages/", {"body": "", "files": files}, format="multipart")
        model = MessageAttachment
    elif kind == "announcement":
        res = client_for(manager).post("/api/v1/announcements/", {"title": "T", "body": "B", "audience": "departments",
                                                                 "departments": [departments["sales"].pk], "files": files}, format="multipart")
        model = AnnouncementAttachment
    elif kind == "receipt":
        res = client_for(staff).post("/api/v1/expenses/claims/", {"title": "Taxi", "category": "travel", "amount": "100",
                                                                  "spent_on": date.today().isoformat(), "files": files}, format="multipart")
        model = ExpenseReceipt
    else:
        res = client_for(admin).post("/api/v1/resources/", {"name": "Room", "type": "room", "photo": files[0]}, format="multipart")
        assert res.status_code == 201, res.data
        return [Resource.objects.get(pk=res.data["id"])]
    assert res.status_code in (200, 201), res.data
    return list(model.objects.order_by("-pk")[: len(files)])


KINDS = ["task", "chat", "announcement", "receipt", "resource"]


@pytest.mark.parametrize("kind", KINDS)
def test_uploaded_photo_is_stored_upright_without_metadata(kind, client_for, admin, manager, staff, task, departments):
    [row] = store(kind, client_for, admin, manager, staff, task, departments, [phone_jpeg()])
    stored = row.photo if kind == "resource" else row.file
    assert stored.name.endswith(".jpg")
    with opened(stored) as im:
        assert im.format == "JPEG" and is_clean_and_upright(im)
    with opened(row.thumbnail) as thumb:
        assert thumb.size[1] > thumb.size[0]  # the thumbnail is upright too
    if kind != "resource":
        assert row.size == stored.size  # the size shown is the stored file's


@pytest.mark.parametrize("kind", ["task", "chat", "announcement", "receipt"])
def test_other_files_are_stored_exactly_as_uploaded(kind, client_for, admin, manager, staff, task, departments):
    pdf = b"%PDF-1.4\n% made by a scanner at 31.5,74.3\n%%EOF\n"
    text = "date,amount\n2026-10-01,100\n".encode()
    rows = store(kind, client_for, admin, manager, staff, task, departments, [upload("scan.pdf", pdf), upload("list.csv", text)])
    stored = {r.original_name: read(r.file) for r in rows}
    assert stored == {"scan.pdf": pdf, "list.csv": text}
    assert all(not r.thumbnail for r in rows)


def test_a_phone_mpo_jpeg_is_accepted(client_for, staff, task):
    buf = io.BytesIO()
    picture().save(buf, "MPO", save_all=True, append_images=[picture((100, 50))], exif=exif(6))
    res = client_for(staff).post(f"/api/v1/tasks/{task.pk}/attachments/", {"files": [upload("IMG_2.jpg", buf.getvalue())]}, format="multipart")
    assert res.status_code == 201, res.data
    with opened(TaskAttachment.objects.latest("pk").file) as im:
        assert im.format == "JPEG" and is_clean_and_upright(im)


# ================================================================ the cleanup command


def raw(model_row, field, name, data):
    """Store a file as earlier versions did: exactly as uploaded."""
    getattr(model_row, field).save(name, ContentFile(data), save=False)


def dirty_jpeg():
    return phone_jpeg().read()


def run(*args):
    out, err = io.StringIO(), io.StringIO()
    call_command("clean_stored_images", *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


def test_cleanup_command_dry_run_then_clean_then_nothing(staff, task):
    def attach(name, data, kind):
        a = TaskAttachment(task=task, original_name=name, size=len(data), content_type="x", kind=kind, uploaded_by=staff)
        raw(a, "file", f"upload.{name.rsplit('.', 1)[1]}", data)
        if kind == "image":
            raw(a, "thumbnail", "thumb.webp", b"old thumbnail")
        a.save()
        return a

    photo = attach("IMG_1.jpg", dirty_jpeg(), "image")
    clean_buf = io.BytesIO()
    picture().save(clean_buf, "PNG")
    tidy = attach("chart.png", clean_buf.getvalue(), "image")
    pdf = attach("scan.pdf", b"%PDF-1.4\n%%EOF\n", "pdf")
    broken = attach("broken.png", b"\x89PNG\r\n\x1a\n not really", "image")
    room = Resource.objects.create(name="Room", type="room")
    raw(room, "photo", "photo.jpg", dirty_jpeg())
    room.save()
    before = {a.pk: (a.file.name, read(a.file)) for a in (photo, tidy, pdf, broken)}

    out, err = run("--dry-run")
    assert "Dry run, nothing changed. 4 image(s): 2 to clean, 1 already clean; 1 other file(s) skipped, 0 missing, 1 failed" in out
    assert "can't open" in err and "broken.png" in err
    for a in (photo, tidy, pdf, broken):
        a.refresh_from_db()
        assert (a.file.name, read(a.file)) == before[a.pk]  # nothing touched

    out, _err = run()
    assert "4 image(s): 2 cleaned, 1 already clean; 1 other file(s) skipped, 0 missing, 1 failed" in out
    photo.refresh_from_db()
    room.refresh_from_db()
    for stored, thumb in ((photo.file, photo.thumbnail), (room.photo, room.thumbnail)):
        with opened(stored) as im:
            assert im.format == "JPEG" and is_clean_and_upright(im)
        with opened(thumb) as t:
            assert t.size[1] > t.size[0]
    assert photo.size == photo.file.size and photo.file.name != before[photo.pk][0]
    assert not photo.file.storage.exists(before[photo.pk][0])  # the old file is gone
    for a in (tidy, pdf, broken):
        a.refresh_from_db()
        assert (a.file.name, read(a.file)) == before[a.pk]

    names = (photo.file.name, room.photo.name)
    out, _err = run()  # a second run changes nothing
    assert "4 image(s): 0 cleaned, 3 already clean; 1 other file(s) skipped, 0 missing, 1 failed" in out
    photo.refresh_from_db()
    room.refresh_from_db()
    assert (photo.file.name, room.photo.name) == names


def test_cleanup_command_reports_missing_files(staff, task):
    a = TaskAttachment(task=task, original_name="gone.jpg", size=1, content_type="image/jpeg", kind="image", uploaded_by=staff)
    raw(a, "file", "upload.jpg", dirty_jpeg())
    a.save()
    a.file.storage.delete(a.file.name)
    out, err = run()
    assert "1 image(s): 0 cleaned, 0 already clean; 0 other file(s) skipped, 1 missing, 0 failed" in out and "missing" in err and "gone.jpg" in err
