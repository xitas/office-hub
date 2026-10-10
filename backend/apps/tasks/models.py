from datetime import datetime

from django.conf import settings
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
