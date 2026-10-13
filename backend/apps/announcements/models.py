"""Office announcements: a board everyone reads, with read receipts.

- Audience: everyone, or chosen departments. Admins post to anyone; managers to their own department.
- Pinned announcements come first; after the optional expiry date an announcement moves to the archive.
- The body uses light formatting (see formatting.py): **bold**, "- " / "1. " lists and links.
- Files follow the task-file rules and are stored privately.
- Each person's first opening is recorded (AnnouncementRead), so the author and admins see who has read it.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.tasks.models import private_storage


class Announcement(models.Model):
    class Audience(models.TextChoices):
        EVERYONE = "everyone", _("Everyone")
        DEPARTMENTS = "departments", _("Chosen departments")

    title = models.CharField(max_length=200)
    body = models.TextField()
    audience = models.CharField(max_length=12, choices=Audience.choices, default=Audience.EVERYONE)
    departments = models.ManyToManyField("accounts.Department", blank=True, related_name="announcements")
    pinned = models.BooleanField(default=False)
    expires_on = models.DateField(null=True, blank=True, help_text="Moves to the archive after this day.")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="announcements")
    published_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-pinned", "-published_at", "-id"]
        verbose_name = _("announcement")
        verbose_name_plural = _("announcements")

    def __str__(self):
        return self.title


def announcement_file_path(instance, filename):
    # Random names: nothing about the original name can be guessed from the path.
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"announcements/{timezone.now():%Y/%m}/{uuid.uuid4().hex}.{ext}"


class AnnouncementAttachment(models.Model):
    """A file on an announcement: private storage, downloaded only by people who can see the announcement."""

    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to=announcement_file_path, storage=private_storage, max_length=200)
    thumbnail = models.FileField(upload_to=announcement_file_path, storage=private_storage, max_length=200, blank=True)
    original_name = models.CharField(max_length=255)
    size = models.PositiveIntegerField()
    content_type = models.CharField(max_length=100)
    kind = models.CharField(max_length=10)  # image | pdf | office | text | zip (see apps.tasks.files)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        verbose_name = _("announcement attachment")
        verbose_name_plural = _("announcement attachments")

    def __str__(self):
        return self.original_name


class AnnouncementRead(models.Model):
    """When someone first opened an announcement."""

    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE, related_name="reads")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="announcement_reads")
    read_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["announcement", "user"], name="announcement_read_once")]
        indexes = [models.Index(fields=["user", "announcement"], name="announcement_read_user_idx")]
        verbose_name = _("announcement read")
        verbose_name_plural = _("announcement reads")

    def __str__(self):
        return f"{self.user} read {self.announcement}"
