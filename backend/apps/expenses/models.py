"""Expense claims: money someone spent for the office, with receipts, approval and payment.

- Anyone claims their own expenses (what, category, amount in the office currency, the day it was spent)
  and attaches receipts (task-file rules, stored privately).
- Managers of the claimant's department approve or reject (admins when there is none, or for a manager's own
  claim; an admin's own claim goes to the other admins, and is approved at once only if there are none).
- Admins mark approved claims paid (reimbursed). The claimant is told at each step.
- Claims are private: the claimant, their department's managers and admins see them.
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.tasks.models import private_storage


class Expense(models.Model):
    class Category(models.TextChoices):
        TRAVEL = "travel", _("Travel and transport")
        FUEL = "fuel", _("Fuel")
        MEALS = "meals", _("Meals")
        CLIENT = "client", _("Client entertainment")
        SUPPLIES = "supplies", _("Office supplies")
        BILLS = "bills", _("Bills and utilities")
        REPAIRS = "repairs", _("Repairs and maintenance")
        OTHER = "other", _("Other")

    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting for approval")
        APPROVED = "approved", _("Approved, to pay")
        REJECTED = "rejected", _("Rejected")
        CANCELLED = "cancelled", _("Cancelled")
        PAID = "paid", _("Paid")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="expenses")
    title = models.CharField(max_length=120)
    category = models.CharField(max_length=10, choices=Category.choices, default=Category.OTHER)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    spent_on = models.DateField()
    description = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=300, blank=True)
    paid_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    paid_at = models.DateTimeField(null=True, blank=True)
    payment_note = models.CharField(max_length=200, blank=True, help_text="Cash, bank transfer reference…")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-spent_on", "-id"]
        indexes = [models.Index(fields=["user", "spent_on"], name="expense_user_spent_idx")]
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name="expense_amount_positive")]
        verbose_name = _("expense")
        verbose_name_plural = _("expenses")

    def __str__(self):
        return f"{self.title} ({self.currency} {self.amount})"


def receipt_path(instance, filename):
    # Random names: nothing about the original name can be guessed from the path.
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"receipts/{timezone.now():%Y/%m}/{uuid.uuid4().hex}.{ext}"


class ExpenseReceipt(models.Model):
    """A receipt on a claim: private storage, downloaded only by people who can see the claim."""

    expense = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name="receipts")
    file = models.FileField(upload_to=receipt_path, storage=private_storage, max_length=200)
    thumbnail = models.FileField(upload_to=receipt_path, storage=private_storage, max_length=200, blank=True)
    original_name = models.CharField(max_length=255)
    size = models.PositiveIntegerField()
    content_type = models.CharField(max_length=100)
    kind = models.CharField(max_length=10)  # image | pdf | office | text | zip (see apps.tasks.files)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        verbose_name = _("expense receipt")
        verbose_name_plural = _("expense receipts")

    def __str__(self):
        return self.original_name
