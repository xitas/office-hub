"""Errands and deliveries: someone from the office takes or fetches something, or goes to the bank.

- An errand says what (a courier to send, a document to pick up, a delivery to make, a bank visit, something else),
  where (a contact, company or vendor, e.g. the courier company, or just a place, with an optional pin for the map),
  by when, and who does it (the runner). It can carry out a task.
- Anyone asks for an errand for their department. They can give it to a colleague in the department (managers and
  admins as for tasks), or leave it open for someone to take; the department's managers hear about open ones.
- The runner marks it "on the way", then done (with a note, a tracking or receipt number and proof photos, location
  stripped) or not done (why). Each step is kept (ErrandUpdate) and whoever asked is told. A reminder goes to the
  runner before it's due (Celery Beat).
- Seen by whoever asked, the runner, the department's managers and admins; open errands also by the department.
"""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.geo import pin_constraint, pin_fields
from apps.tasks.models import private_storage


class Errand(models.Model):
    class Kind(models.TextChoices):
        COURIER = "courier", _("Courier to send")
        PICKUP = "pickup", _("Document pickup")
        DELIVERY = "delivery", _("Delivery")
        BANK = "bank", _("Bank visit")
        OTHER = "other", _("Other errand")

    class Status(models.TextChoices):
        OPEN = "open", _("Waiting for someone")
        ASSIGNED = "assigned", _("To do")
        ON_THE_WAY = "on_the_way", _("On the way")
        DONE = "done", _("Done")
        FAILED = "failed", _("Not done")
        CANCELLED = "cancelled", _("Cancelled")

    ACTIVE = (Status.OPEN, Status.ASSIGNED, Status.ON_THE_WAY)
    FINISHED = (Status.DONE, Status.FAILED)

    title = models.CharField(max_length=150)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.OTHER)
    details = models.TextField(blank=True)
    contact = models.ForeignKey("contacts.Contact", null=True, blank=True, on_delete=models.SET_NULL, related_name="errands")
    company = models.ForeignKey("contacts.Company", null=True, blank=True, on_delete=models.SET_NULL, related_name="errands")
    vendor = models.ForeignKey("vendors.Vendor", null=True, blank=True, on_delete=models.SET_NULL, related_name="errands")
    place_name = models.CharField(max_length=150, blank=True)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    latitude, longitude = pin_fields()  # where to go, for the map (optional)
    due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    department = models.ForeignKey("accounts.Department", null=True, blank=True, on_delete=models.SET_NULL, related_name="errands",
                                   help_text="Whose errand it is (the department of whoever asked)")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="errands_requested")
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="errands")
    task = models.ForeignKey("tasks.Task", null=True, blank=True, on_delete=models.SET_NULL, related_name="errands",
                             help_text="The task this errand carries out")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)
    reference = models.CharField(max_length=100, blank=True, help_text="Tracking number, receipt or deposit slip number")
    outcome_note = models.CharField(max_length=500, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    # "Due soon" was sent to the runner for this due time (once).
    reminded_due = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["due_at", "id"]
        indexes = [models.Index(fields=["department", "status"], name="errand_dept_status_idx")]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(contact__isnull=True, company__isnull=True) | Q(contact__isnull=True, vendor__isnull=True)
                    | Q(company__isnull=True, vendor__isnull=True)
                ),
                name="errand_at_most_one_record",
            ),
            models.CheckConstraint(condition=~Q(status="assigned") | Q(assigned_to__isnull=False), name="errand_assigned_has_runner"),
            pin_constraint("errand_pin_valid"),
        ]
        verbose_name = _("errand")
        verbose_name_plural = _("errands")

    def __str__(self):
        return self.title

    @property
    def place(self) -> str:
        if self.contact_id:
            return self.contact.full_name
        if self.company_id:
            return self.company.name
        if self.vendor_id:
            return self.vendor.name
        return self.place_name


class ErrandUpdate(models.Model):
    """One step of an errand (asked, given to someone, taken, on the way, done, not done, cancelled), with a note."""

    errand = models.ForeignKey(Errand, on_delete=models.CASCADE, related_name="updates")
    status = models.CharField(max_length=10, choices=Errand.Status.choices)
    note = models.CharField(max_length=500, blank=True)
    by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["at", "id"]
        verbose_name = _("errand update")
        verbose_name_plural = _("errand updates")


def photo_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    return f"errands/{timezone.now():%Y/%m}/{uuid.uuid4().hex}.{ext}"


class ErrandPhoto(models.Model):
    """Proof (a receipt, the parcel handed over): private storage, re-encoded with no EXIF or GPS kept."""

    errand = models.ForeignKey(Errand, on_delete=models.CASCADE, related_name="photos")
    file = models.FileField(upload_to=photo_path, storage=private_storage, max_length=200)
    thumbnail = models.FileField(upload_to=photo_path, storage=private_storage, max_length=200, blank=True)
    original_name = models.CharField(max_length=255)
    size = models.PositiveIntegerField()
    content_type = models.CharField(max_length=100)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        verbose_name = _("errand photo")
        verbose_name_plural = _("errand photos")

    def __str__(self):
        return self.original_name
