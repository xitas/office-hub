"""Vendors and suppliers: one office-wide directory of the local businesses and people the office buys from
or calls on (stationers, printers, courier services, electricians…).

- Everyone sees the active vendors and adds new ones; anyone can correct details (audited). Managers and
  admins mark a vendor preferred or inactive, and delete one that nothing refers to (otherwise it's made
  inactive, so history keeps its name). Admins manage the service categories.
- Vendors connect to the rest of the app instead of copying it: a supply item has a usual supplier, a
  purchase request where to buy it, an expense claim who was paid, and calls, messages and notes with a
  vendor are logged on the shared timeline (TimelineEntry.vendor), with follow-ups and message templates.
"""
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.geo import pin_constraint, pin_fields
from apps.core.phones import normalize_phone


class VendorCategory(models.Model):
    name = models.CharField(max_length=80, unique=True)
    name_ur = models.CharField(max_length=80, blank=True, help_text="Name shown in Urdu (optional)")
    position = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["position", "name"]
        verbose_name = _("vendor category")
        verbose_name_plural = _("vendor categories")

    def __str__(self):
        return self.name


class Vendor(models.Model):
    name = models.CharField(max_length=150, db_index=True)
    categories = models.ManyToManyField(VendorCategory, blank=True, related_name="vendors")
    contact_person = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    whatsapp = models.CharField(max_length=30, blank=True, help_text="If different from the phone")
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True, db_index=True)
    areas = models.CharField(max_length=255, blank=True, help_text="Areas served, e.g. Gulberg, DHA, Model Town")
    latitude, longitude = pin_fields()  # where it is, for the map (optional)
    payment_terms = models.CharField(max_length=200, blank=True, help_text="Cash on delivery, 30 days credit…")
    notes = models.TextField(blank=True)
    rating = models.PositiveSmallIntegerField(null=True, blank=True, help_text="1–5")
    preferred = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    # Digits-only international forms, so "0300-1234567" and "+92 300 1234567" find the same vendor.
    phone_digits = models.CharField(max_length=30, blank=True, db_index=True, editable=False)
    whatsapp_digits = models.CharField(max_length=30, blank=True, db_index=True, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(condition=models.Q(rating__isnull=True) | models.Q(rating__gte=1, rating__lte=5), name="vendor_rating_1_to_5"),
            pin_constraint("vendor_pin_valid"),
        ]
        verbose_name = _("vendor")
        verbose_name_plural = _("vendors")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.phone_digits = normalize_phone(self.phone)
        self.whatsapp_digits = normalize_phone(self.whatsapp)
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = {*kwargs["update_fields"], "phone_digits", "whatsapp_digits"}
        super().save(*args, **kwargs)

    @property
    def first_name(self) -> str:
        """For message templates: the contact person's first name ({contact.first_name})."""
        return (self.contact_person or "").split(" ")[0]
