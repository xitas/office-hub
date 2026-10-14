"""Rooms and other resources, and their bookings.

- A resource (meeting room, projector, vehicle, other) is bookable by everyone or by chosen
  departments, and may need approval (e.g. vehicles). Admins manage resources.
- A booking holds a resource from `start` to `end` (stored in UTC, shown in the office time zone).
  Confirmed and pending bookings of the same resource never overlap: PostgreSQL enforces it with an
  exclusion constraint (migration 0002), so two people booking at the same moment can't both win;
  the code also checks (with a row lock) to give a clear message, and covers SQLite in tests.
- Weekly repeats share a BookingSeries; each date is its own booking (cancel one or the rest).
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.tasks.models import private_storage


def resource_photo_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"resources/{uuid.uuid4().hex}.{ext}"


class Resource(models.Model):
    class Type(models.TextChoices):
        ROOM = "room", _("Meeting room")
        PROJECTOR = "projector", _("Projector")
        VEHICLE = "vehicle", _("Vehicle")
        OTHER = "other", _("Other")

    class BookableBy(models.TextChoices):
        EVERYONE = "everyone", _("Everyone")
        DEPARTMENTS = "departments", _("Chosen departments")

    name = models.CharField(max_length=120)
    type = models.CharField(max_length=12, choices=Type.choices, default=Type.ROOM, db_index=True)
    capacity = models.PositiveSmallIntegerField(null=True, blank=True)  # rooms: people
    location = models.CharField(max_length=150, blank=True)
    description = models.TextField(blank=True)
    photo = models.FileField(upload_to=resource_photo_path, storage=private_storage, max_length=200, blank=True)
    thumbnail = models.FileField(upload_to=resource_photo_path, storage=private_storage, max_length=200, blank=True)
    bookable_by = models.CharField(max_length=12, choices=BookableBy.choices, default=BookableBy.EVERYONE)
    departments = models.ManyToManyField("accounts.Department", blank=True, related_name="resources")
    needs_approval = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["type", "name"]
        verbose_name = _("resource")
        verbose_name_plural = _("resources")

    def __str__(self):
        return self.name


class BookingSeries(models.Model):
    """A weekly repeat: the same time on chosen weekdays until a date."""

    weekdays = models.JSONField(default=list)  # 0 = Monday … 6 = Sunday
    until = models.DateField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("booking series")
        verbose_name_plural = _("booking series")


class Booking(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = "confirmed", _("Confirmed")
        PENDING = "pending", _("Pending approval")
        REJECTED = "rejected", _("Rejected")
        CANCELLED = "cancelled", _("Cancelled")

    # These hold the resource; rejected and cancelled bookings free it.
    HOLDING = (Status.CONFIRMED, Status.PENDING)

    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name="bookings")
    title = models.CharField(max_length=150)
    start = models.DateTimeField()
    end = models.DateTimeField()
    booked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bookings")
    attendees = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="booking_invites")
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CONFIRMED, db_index=True)
    series = models.ForeignKey(BookingSeries, null=True, blank=True, on_delete=models.SET_NULL, related_name="bookings")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.CharField(max_length=300, blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    cancelled_at = models.DateTimeField(null=True, blank=True)
    # The start time the 15-minute reminder went out for (a moved booking gets a new one).
    reminded_start = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start", "id"]
        indexes = [models.Index(fields=["resource", "start"], name="booking_resource_start_idx")]
        constraints = [models.CheckConstraint(condition=models.Q(end__gt=models.F("start")), name="booking_ends_after_start")]
        verbose_name = _("booking")
        verbose_name_plural = _("bookings")

    def __str__(self):
        return f"{self.title} ({self.resource})"

    @property
    def is_past(self):
        return self.end <= timezone.now()
