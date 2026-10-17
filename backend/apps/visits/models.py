"""Field visits: someone from the office going out to a client, a company, a vendor or another place.

- A visit names who or where (a contact, a company or a vendor, or just a place), the address, an optional
  pin (latitude/longitude of the place, used by the map in slices 3 and 5), when (office time zone), who goes
  (one person responsible, optional companions) and why. It can be linked to the task it carries out
  (e.g. a follow-up), and it shows on the record's timeline and on the calendar.
- Staff plan their own visits; managers plan for their department and admins for anyone. With the
  Organization setting on, a staff member's own visit waits for a department manager's approval (admins
  when there is none). Visits are done or cancelled; visit reports and check-in come in later slices.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


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
