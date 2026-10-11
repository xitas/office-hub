from datetime import datetime

import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.db.models import Case, IntegerField, Q, Value, When
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel
from apps.core.office_time import office_datetime, office_tz


class Task(TimeStampedModel):
    class Priority(models.TextChoices):
        LOW = "low", _("Low")
        MEDIUM = "medium", _("Medium")
        HIGH = "high", _("High")
        URGENT = "urgent", _("Urgent")

    class Status(models.TextChoices):
        TODO = "todo", _("To do")
        IN_PROGRESS = "in_progress", _("In progress")
        REVIEW = "review", _("Review")
        DONE = "done", _("Done")

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    assignees = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="tasks", blank=True)
    due_date = models.DateField(null=True, blank=True, db_index=True)
    due_time = models.TimeField(null=True, blank=True)  # optional; a date alone means "by the end of that day"
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TODO, db_index=True)
    # Optional link to a client record (fuller linking comes later).
    contact = models.ForeignKey("contacts.Contact", null=True, blank=True, on_delete=models.SET_NULL, related_name="tasks")
    company = models.ForeignKey("contacts.Company", null=True, blank=True, on_delete=models.SET_NULL, related_name="tasks")
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", editable=False
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("task")
        verbose_name_plural = _("tasks")
        indexes = [models.Index(fields=["status", "due_date"])]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        # completed_at follows the status: set when a task becomes Done, cleared when it is reopened.
        if self.status == self.Status.DONE and self.completed_at is None:
            self.completed_at = timezone.now()
        elif self.status != self.Status.DONE:
            self.completed_at = None
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = {*kwargs["update_fields"], "completed_at"}
        super().save(*args, **kwargs)

    @property
    def due_at(self):
        """When the task is due (end of the day when no time is set), in the office time zone."""
        if self.due_date is None:
            return None
        return office_datetime(self.due_date, self.due_time or datetime.max.time())

    @property
    def is_overdue(self) -> bool:
        return self.status != self.Status.DONE and self.due_at is not None and self.due_at < timezone.now()


PRIORITY_RANK = Case(
    When(priority=Task.Priority.URGENT, then=Value(4)),
    When(priority=Task.Priority.HIGH, then=Value(3)),
    When(priority=Task.Priority.MEDIUM, then=Value(2)),
    default=Value(1),
    output_field=IntegerField(),
)


def overdue_q(now=None) -> Q:
    """Open tasks whose due date (and time, if set) has passed, by the office clock."""
    now = (now or timezone.now()).astimezone(office_tz())
    today, current = now.date(), now.time()
    return ~Q(status=Task.Status.DONE) & (
        Q(due_date__lt=today) | Q(due_date=today, due_time__isnull=False, due_time__lt=current)
    )


class ChecklistItem(models.Model):
    """One subtask on a task's checklist, kept in `position` order."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="checklist")
    text = models.CharField(max_length=300)
    done = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)
    done_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    done_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = _("checklist item")
        verbose_name_plural = _("checklist items")

    def __str__(self):
        return self.text


class TaskComment(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    # Mentions are written as @[Full Name](user:12) so they survive renames and render as chips.
    body = models.TextField(blank=True)
    mentions = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name = _("comment")
        verbose_name_plural = _("comments")

    def __str__(self):
        return self.body[:40]


def attachment_path(instance, filename):
    # Random names: nothing about the original name (or other files) can be guessed from the path.
    import uuid

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    now = timezone.now()
    return f"tasks/{now:%Y/%m}/{uuid.uuid4().hex}.{ext}"


class PrivateStorage(FileSystemStorage):
    """Files under PRIVATE_MEDIA_ROOT: outside MEDIA_ROOT, so never served directly (downloads go through
    a permission check). The folder is read from settings on every use, so tests can point it elsewhere."""

    def __init__(self):
        super().__init__(base_url=None)

    @property
    def base_location(self):
        return str(settings.PRIVATE_MEDIA_ROOT)

    @property
    def location(self):
        return os.path.abspath(self.base_location)


def private_storage():
    return PrivateStorage()


class TaskAttachment(models.Model):
    class Kind(models.TextChoices):
        IMAGE = "image", _("Image")
        PDF = "pdf", _("PDF")
        OFFICE = "office", _("Office document")
        TEXT = "text", _("Text")
        ZIP = "zip", _("ZIP archive")

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="attachments")
    comment = models.ForeignKey(TaskComment, null=True, blank=True, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to=attachment_path, storage=private_storage, max_length=200)
    thumbnail = models.FileField(upload_to=attachment_path, storage=private_storage, max_length=200, blank=True)
    original_name = models.CharField(max_length=255)
    size = models.PositiveIntegerField()
    content_type = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name = _("attachment")
        verbose_name_plural = _("attachments")

    def __str__(self):
        return self.original_name


class TaskActivity(models.Model):
    """Changes shown on the task's timeline next to comments (status, assignees, due date, checklist, files)."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="activity")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    kind = models.CharField(max_length=30)  # created, status, assignees, due, priority, title, checklist_*, attachment_*
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name = _("task activity")
        verbose_name_plural = _("task activity")
