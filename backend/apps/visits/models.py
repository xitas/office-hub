"""Field visits: someone from the office going out to a client, a company, a vendor or another place.

- A visit names who or where (a contact, a company or a vendor, or just a place), the address, an optional
  pin (latitude/longitude of the place, used by the map in slices 3 and 5), when (office time zone), who goes
  (one person responsible, optional companions) and why. It can be linked to the task it carries out
  (e.g. a follow-up), and it shows on the record's timeline and on the calendar.
- Staff plan their own visits; managers plan for their department and admins for anyone. With the
  Organization setting on, a staff member's own visit waits for a department manager's approval (admins
  when there is none). Visits are done or cancelled; visit reports come in a later slice.
- The people going check in and out at the visit (VisitCheck). Location is taken only then, never in the
  background, and only if the person allows it; otherwise the check-in is marked "no location".
- After the visit, a report (VisitReport): how it went, notes, photos (VisitPhoto, location metadata stripped)
  and the next action, which becomes a follow-up task. Writing it marks the visit done.
"""
import uuid

from django.conf import settings
from django.utils import timezone
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.tasks.models import private_storage


class Visit(models.Model):
    class Purpose(models.TextChoices):
        MEETING = "meeting", _("Client meeting")
        DELIVERY = "delivery", _("Delivery or pickup")
        SITE = "site", _("Site survey or inspection")
        COLLECTION = "collection", _("Payment collection")
        SUPPORT = "support", _("Service or support")
        OTHER = "other", _("Other")

    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting for approval")
        PLANNED = "planned", _("Planned")
        DONE = "done", _("Done")
        CANCELLED = "cancelled", _("Cancelled")
        REJECTED = "rejected", _("Not approved")

    OPEN = (Status.PENDING, Status.PLANNED)

    title = models.CharField(max_length=150)
    purpose = models.CharField(max_length=12, choices=Purpose.choices, default=Purpose.MEETING)
    contact = models.ForeignKey("contacts.Contact", null=True, blank=True, on_delete=models.SET_NULL, related_name="visits")
    company = models.ForeignKey("contacts.Company", null=True, blank=True, on_delete=models.SET_NULL, related_name="visits")
    vendor = models.ForeignKey("vendors.Vendor", null=True, blank=True, on_delete=models.SET_NULL, related_name="visits")
    place_name = models.CharField(max_length=150, blank=True, help_text="Where, when it isn't a contact, company or vendor")
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    # The place's pin (not a person's position): optional, kept with the visit.
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    start = models.DateTimeField(db_index=True)
    end = models.DateTimeField()
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="visits")
    companions = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="visits_joined")
    notes = models.TextField(blank=True)
    task = models.ForeignKey("tasks.Task", null=True, blank=True, on_delete=models.SET_NULL, related_name="visits",
                             help_text="The task this visit carries out, e.g. a follow-up")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PLANNED, db_index=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=300, blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    closed_at = models.DateTimeField(null=True, blank=True)
    close_note = models.CharField(max_length=300, blank=True, help_text="Why it was cancelled, or a word on how it went")
    reminded_start = models.DateTimeField(null=True, blank=True)
    # "No check-in yet" was sent for this start time (once).
    check_in_reminded_start = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start", "id"]
        indexes = [models.Index(fields=["assigned_to", "start"], name="visit_person_start_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(end__gt=models.F("start")), name="visit_ends_after_start"),
            models.CheckConstraint(
                condition=(
                    Q(contact__isnull=True, company__isnull=True) | Q(contact__isnull=True, vendor__isnull=True)
                    | Q(company__isnull=True, vendor__isnull=True)
                ),
                name="visit_at_most_one_record",
            ),
            models.CheckConstraint(
                condition=Q(latitude__isnull=True, longitude__isnull=True)
                | Q(latitude__gte=-90, latitude__lte=90, longitude__gte=-180, longitude__lte=180),
                name="visit_pin_valid",
            ),
        ]
        verbose_name = _("field visit")
        verbose_name_plural = _("field visits")

    def __str__(self):
        return self.title

    @property
    def place(self) -> str:
        """Who or where: the contact, company or vendor, or the place's name."""
        if self.contact_id:
            return self.contact.full_name
        if self.company_id:
            return self.company.name
        if self.vendor_id:
            return self.vendor.name
        return self.place_name


class VisitCheck(models.Model):
    """One person's check-in and check-out at a visit, with where they were (if they allowed it).

    Coordinates are personal data: only the person, their department's managers and admins see them (enforced in
    the API), and they're removed after 90 days by a scheduled job; the times and the visit stay.
    """

    class Location(models.TextChoices):
        RECORDED = "recorded", _("Location recorded")
        DECLINED = "declined", _("Location not shared")
        UNAVAILABLE = "unavailable", _("Location unavailable")

    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="checks")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="visit_checks")
    checked_in_at = models.DateTimeField()
    in_location = models.CharField(max_length=12, choices=Location.choices)
    in_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    in_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    in_accuracy = models.PositiveIntegerField(null=True, blank=True, help_text="Metres, as the device reported it")
    checked_out_at = models.DateTimeField(null=True, blank=True)
    out_location = models.CharField(max_length=12, choices=Location.choices, blank=True)
    out_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    out_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    out_accuracy = models.PositiveIntegerField(null=True, blank=True)
    location_removed_at = models.DateTimeField(null=True, blank=True, help_text="Coordinates removed after 90 days")

    class Meta:
        ordering = ["checked_in_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["visit", "user"], name="one_visit_check_per_person"),
            models.CheckConstraint(condition=Q(checked_out_at__isnull=True) | Q(checked_out_at__gte=models.F("checked_in_at")),
                                   name="visit_check_out_after_in"),
        ]
        indexes = [models.Index(fields=["checked_in_at"], name="visit_check_in_idx")]
        verbose_name = _("visit check-in")
        verbose_name_plural = _("visit check-ins")

    def __str__(self):
        return f"{self.user} @ {self.visit}"


class VisitReport(models.Model):
    """How a visit went, written by someone who went (or their manager). Writing it marks the visit done.

    Connected rather than copied: on a contact's, company's or vendor's visit the report is also a timeline entry
    (kind "visit": the record's history, the communication log, "last contacted"), and the next action becomes a
    follow-up task through the timeline's follow-ups (completing the task marks the follow-up done). A lead's
    status can be moved from the report (a normal status change, with its history).
    """

    class Outcome(models.TextChoices):
        GOOD = "good", _("Went well")
        FOLLOW_UP = "follow_up", _("Needs follow-up")
        NO_RESULT = "no_result", _("No result")
        NOT_MET = "not_met", _("Couldn't meet")

    visit = models.OneToOneField(Visit, on_delete=models.CASCADE, related_name="report")
    outcome = models.CharField(max_length=12, choices=Outcome.choices)
    notes = models.TextField(blank=True)
    next_action = models.CharField(max_length=200, blank=True)
    next_action_on = models.DateField(null=True, blank=True)
    # The record's timeline entry for this report (none for a visit to a place).
    entry = models.OneToOneField("timeline.TimelineEntry", null=True, blank=True, on_delete=models.SET_NULL, related_name="visit_report")
    follow_up_task = models.ForeignKey("tasks.Task", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    status_change = models.ForeignKey("contacts.ContactStatusChange", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    written_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    written_at = models.DateTimeField(default=timezone.now)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("visit report")
        verbose_name_plural = _("visit reports")

    def __str__(self):
        return str(self.visit)


def photo_path(instance, filename):
    # Random names: nothing about the original name can be guessed from the path.
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    return f"visits/{timezone.now():%Y/%m}/{uuid.uuid4().hex}.{ext}"


class VisitPhoto(models.Model):
    """A photo on a visit report: private storage (task-file rules), re-encoded so no EXIF or GPS location is kept."""

    report = models.ForeignKey(VisitReport, on_delete=models.CASCADE, related_name="photos")
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
        verbose_name = _("visit photo")
        verbose_name_plural = _("visit photos")

    def __str__(self):
        return self.original_name
