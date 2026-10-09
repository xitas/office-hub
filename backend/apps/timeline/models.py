from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class TimelineEntry(models.Model):
    """A logged interaction (note, call, meeting, ...) on exactly one contact or company.

    Open for extension: `kind` is a key from the type registry (apps.timeline.registry), and
    type-specific data lives in `details` (validated per type there). New modules register new
    kinds without schema changes. Automatic entries (status changes, record created, later tasks
    and messages) are not stored here; they come from registered providers.
    """

    kind = models.CharField(max_length=40, db_index=True)
    contact = models.ForeignKey(
        "contacts.Contact", null=True, blank=True, on_delete=models.CASCADE, related_name="timeline_entries"
    )
    company = models.ForeignKey(
        "contacts.Company", null=True, blank=True, on_delete=models.CASCADE, related_name="timeline_entries"
    )
    summary = models.TextField()
    details = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    follow_up_on = models.DateField(null=True, blank=True, db_index=True)  # reminders come with Tasks
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="timeline_entries"
    )
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]
        verbose_name = _("timeline entry")
        verbose_name_plural = _("timeline entries")
        constraints = [
            models.CheckConstraint(
                condition=(Q(contact__isnull=False) & Q(company__isnull=True)) | (Q(contact__isnull=True) & Q(company__isnull=False)),
                name="timeline_entry_one_target",
            )
        ]

    def __str__(self):
        return f"{self.kind}: {self.summary[:40]}"

    @property
    def target(self):
        return self.contact or self.company
