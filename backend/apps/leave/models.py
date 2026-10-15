"""Leave: types with a yearly allowance, each person's balance per year, and requests.

- A leave type (annual, sick, casual, unpaid…) has days per year (empty = no limit), and may allow half days.
- A balance is one person's allowance for one type and year; it starts at the type's days and an admin
  can change it (carry-over, part-year joiners). Used and pending days are counted from the requests.
- A request covers whole office days (or half of one day). Its days count only working days that
  aren't office holidays (Organization page and the calendar), and are fixed when it's made.
- Managers of the requester's department approve or reject (admins when there is no manager, or for a
  manager's own request); admins' own requests are approved at once.
"""
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class LeaveType(models.Model):
    name = models.CharField(max_length=80)
    name_ur = models.CharField(max_length=80, blank=True, help_text="Name shown in Urdu (optional)")
    days_per_year = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True, help_text="Empty: no limit")
    paid = models.BooleanField(default=True)
    allow_half_days = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    position = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "name"]
        verbose_name = _("leave type")
        verbose_name_plural = _("leave types")

    def __str__(self):
        return self.name


class LeaveBalance(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="leave_balances")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE, related_name="balances")
    year = models.PositiveSmallIntegerField()
    allowance = models.DecimalField(max_digits=5, decimal_places=1, default=Decimal("0"))
    note = models.CharField(max_length=200, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "leave_type", "year"], name="one_leave_balance_per_year")]
        verbose_name = _("leave balance")
        verbose_name_plural = _("leave balances")

    def __str__(self):
        return f"{self.user} {self.leave_type} {self.year}"


class LeaveRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting for approval")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")
        CANCELLED = "cancelled", _("Cancelled")

    class HalfDay(models.TextChoices):
        NONE = "", _("Whole day")
        MORNING = "morning", _("Morning")
        AFTERNOON = "afternoon", _("Afternoon")

    # These count against the balance and block overlapping requests.
    HOLDING = (Status.PENDING, Status.APPROVED)

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="leave_requests")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name="requests")
    start_date = models.DateField()
    end_date = models.DateField()
    half_day = models.CharField(max_length=10, choices=HalfDay.choices, blank=True, default=HalfDay.NONE)
    days = models.DecimalField(max_digits=5, decimal_places=1)
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=300, blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date", "-id"]
        indexes = [models.Index(fields=["user", "start_date"], name="leave_user_start_idx")]
        constraints = [models.CheckConstraint(condition=models.Q(end_date__gte=models.F("start_date")), name="leave_ends_on_or_after_start")]
        verbose_name = _("leave request")
        verbose_name_plural = _("leave requests")

    def __str__(self):
        return f"{self.user} {self.leave_type} {self.start_date}–{self.end_date}"
