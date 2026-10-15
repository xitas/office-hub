"""Attendance: each person's check-in and check-out per office day.

A day's status (present, late, on a field visit, working remotely, on leave, absent, day off) is worked
out from these records, approved leave, the working week and office holidays (see status.py), so
nothing has to be filled in for days off or leave. Field visits (Phase 5) can check people in as
"field" later; for now people choose it when they check in.
"""
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Attendance(models.Model):
    class Mode(models.TextChoices):
        OFFICE = "office", _("In the office")
        FIELD = "field", _("On a field visit")
        REMOTE = "remote", _("Working remotely")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attendance")
    date = models.DateField()
    check_in = models.DateTimeField(null=True, blank=True)
    check_out = models.DateTimeField(null=True, blank=True)
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.OFFICE)
    note = models.CharField(max_length=300, blank=True)
    # Set when a manager or admin corrected the record (the person is told; the change is audited).
    corrected_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    corrected_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "user_id"]
        constraints = [
            models.UniqueConstraint(fields=["user", "date"], name="one_attendance_per_day"),
            models.CheckConstraint(
                condition=models.Q(check_out__isnull=True) | models.Q(check_in__isnull=False, check_out__gt=models.F("check_in")),
                name="attendance_out_after_in",
            ),
        ]
        indexes = [models.Index(fields=["date", "user"], name="attendance_date_user_idx")]
        verbose_name = _("attendance")
        verbose_name_plural = _("attendance")

    def __str__(self):
        return f"{self.user} {self.date}"


class AttendanceReminder(models.Model):
    """One row per reminder sent ("forgot to check in / out"), so nobody is reminded twice a day."""

    class Kind(models.TextChoices):
        CHECK_IN = "in", _("Check-in reminder")
        CHECK_OUT = "out", _("Check-out reminder")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    date = models.DateField()
    kind = models.CharField(max_length=3, choices=Kind.choices)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "date", "kind"], name="one_attendance_reminder")]
