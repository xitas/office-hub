"""Clean images stored before uploads were cleaned: task, chat and announcement attachments, expense receipts and
resource photos were kept exactly as uploaded, so a phone photo could still carry its GPS location and camera details,
and its thumbnail ignored the orientation tag.

Each stored image that still has metadata (or isn't upright) is cleaned the same way new uploads are
(apps.core.photos.clean_image: upright, no EXIF, GPS, XMP or comments, same format and size), its thumbnail made again,
and its size updated; the old file is deleted once the new one is saved. Images that are already clean are left alone,
so running it twice changes nothing the second time. Other files (PDF, Office, ZIP, text) are skipped, and so are
files that are missing or can't be opened (they're counted and listed).

    python manage.py clean_stored_images --dry-run   # what would change
    python manage.py clean_stored_images
"""
import io

from django.core.management.base import BaseCommand
from PIL import Image

from apps.core.photos import clean_image, needs_cleaning
from apps.tasks.files import IMAGE_FORMATS, FileRejected, make_thumbnail


def targets():
    """(model, file field, name for new files) of everything that kept uploads as they came."""
    from apps.announcements.models import AnnouncementAttachment
    from apps.bookings.models import Resource
    from apps.chat.models import MessageAttachment
    from apps.expenses.models import ExpenseReceipt
    from apps.tasks.models import TaskAttachment

    return [(TaskAttachment, "file", "upload"), (MessageAttachment, "file", "upload"), (AnnouncementAttachment, "file", "upload"),
            (ExpenseReceipt, "file", "upload"), (Resource, "photo", "photo")]


class Command(BaseCommand):
    help = "Clean already-stored images (attachments, receipts, resource photos): upright, without GPS, camera or other metadata."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Only report what would be cleaned; change nothing.")

    def handle(self, *args, dry_run=False, **options):
        totals = dict.fromkeys(("images", "cleaned", "already clean", "not images", "missing", "failed"), 0)
        for model, field_name, stem in targets():
            counts = dict.fromkeys(totals, 0)
            for obj in model._default_manager.exclude(**{field_name: ""}).order_by("pk").iterator():
                outcome = self._one(obj, field_name, stem, dry_run)
                counts[outcome] += 1
                if outcome != "not images":
                    counts["images"] += 1
            for key in totals:
                totals[key] += counts[key]
            self.stdout.write(f"  {model._meta.label}.{field_name}: " + self._line(counts, dry_run))
        message = ("Dry run, nothing changed. " if dry_run else "") + self._line(totals, dry_run)
        self.stdout.write(self.style.SUCCESS(message) if not totals["failed"] else self.style.WARNING(message))

    @staticmethod
    def _line(counts, dry_run) -> str:
        cleaned = "to clean" if dry_run else "cleaned"
        return (f"{counts['images']} image(s): {counts['cleaned']} {cleaned}, {counts['already clean']} already clean; "
                f"{counts['not images']} other file(s) skipped, {counts['missing']} missing, {counts['failed']} failed")

    def _one(self, obj, field_name, stem, dry_run) -> str:
        stored = getattr(obj, field_name)
        ext = stored.name.rsplit(".", 1)[-1].lower() if "." in stored.name else ""
        if ext not in IMAGE_FORMATS:
            return "not images"
        which = f"{obj._meta.label} {obj.pk} “{getattr(obj, 'original_name', '') or stored.name}” ({stored.name})"
        if not stored.storage.exists(stored.name):
            self.stderr.write(f"    missing: {which}")
            return "missing"
        try:
            with stored.storage.open(stored.name, "rb") as fh:
                data = io.BytesIO(fh.read())
            data.name = getattr(obj, "original_name", "") or stored.name
            with Image.open(data) as img:
                dirty = needs_cleaning(img)
        except Exception as exc:  # unreadable: leave it as it is
            self.stderr.write(f"    can't open: {which}: {type(exc).__name__}")
            return "failed"
        if not dirty:
            return "already clean"
        if dry_run:
            return "cleaned"
        try:
            content = clean_image(data, ext)
        except FileRejected as exc:
            self.stderr.write(f"    can't clean: {which}: {exc}")
            return "failed"
        old_file, old_thumb = stored.name, getattr(obj, "thumbnail", None) and obj.thumbnail.name
        thumb = make_thumbnail(content)
        stored.save(f"{stem}.{ext}", content, save=False)
        fields = [field_name]
        if hasattr(obj, "thumbnail"):
            obj.thumbnail = ""
            if thumb:
                obj.thumbnail.save("thumb.webp", thumb, save=False)
            fields.append("thumbnail")
        if hasattr(obj, "size"):
            obj.size = content.size
            fields.append("size")
        obj.save(update_fields=fields)
        for name in (old_file, old_thumb):  # only once the new files are saved
            if name:
                stored.storage.delete(name)
        return "cleaned"
