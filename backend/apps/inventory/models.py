"""Office supplies: items in stock, every change to the count, and purchase requests.

- An item has a quantity and a reorder level; at or below that level it's "low" and the people who look
  after supplies (managers and admins) are alerted once when it drops there.
- Every change to the quantity is a StockMovement (received, used, count corrected), so the history explains it.
- Anyone asks for something to be bought (an item in the list or a new one). Managers of the requester's
  department approve or reject (admins when there is none, or for a manager's own request; an admin's own
  request is approved at once). When it arrives, a manager or admin marks it received, which adds it to stock.
"""
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class SupplyItem(models.Model):
    class Category(models.TextChoices):
        STATIONERY = "stationery", _("Stationery")
        PRINTING = "printing", _("Printing and IT")
        CLEANING = "cleaning", _("Cleaning")
        KITCHEN = "kitchen", _("Kitchen and refreshments")
        FIRST_AID = "first_aid", _("First aid")
        OTHER = "other", _("Other")

    name = models.CharField(max_length=100)
    name_ur = models.CharField(max_length=100, blank=True, help_text="Name shown in Urdu (optional)")
    category = models.CharField(max_length=12, choices=Category.choices, default=Category.STATIONERY)
    unit = models.CharField(max_length=30, default="piece", help_text="box, ream, packet, bottle…")
    quantity = models.PositiveIntegerField(default=0)
    reorder_level = models.PositiveIntegerField(default=0, help_text="Low stock at or below this quantity")
    location = models.CharField(max_length=100, blank=True)
    notes = models.CharField(max_length=300, blank=True)
    supplier = models.ForeignKey("vendors.Vendor", null=True, blank=True, on_delete=models.SET_NULL, related_name="supplies",
                                 help_text="Where it's usually bought")
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("supply item")
        verbose_name_plural = _("supply items")

    def __str__(self):
        return self.name

    @property
    def is_low(self) -> bool:
        return self.quantity <= self.reorder_level


class PurchaseRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("Waiting for approval")
        APPROVED = "approved", _("Approved, to buy")
        REJECTED = "rejected", _("Rejected")
        CANCELLED = "cancelled", _("Cancelled")
        RECEIVED = "received", _("Received")

    item = models.ForeignKey(SupplyItem, null=True, blank=True, on_delete=models.SET_NULL, related_name="purchase_requests")
    item_name = models.CharField(max_length=100, help_text="The item's name, or what to buy when it isn't in the list")
    quantity = models.PositiveIntegerField()
    unit = models.CharField(max_length=30, blank=True)
    reason = models.CharField(max_length=500, blank=True)
    estimated_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    vendor = models.ForeignKey("vendors.Vendor", null=True, blank=True, on_delete=models.SET_NULL, related_name="purchase_requests",
                               help_text="Where to buy it (or where it was bought)")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="purchase_requests")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=300, blank=True)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    received_at = models.DateTimeField(null=True, blank=True)
    received_quantity = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gt=0), name="purchase_quantity_positive")]
        verbose_name = _("purchase request")
        verbose_name_plural = _("purchase requests")

    def __str__(self):
        return f"{self.quantity} × {self.item_name}"


class StockMovement(models.Model):
    class Kind(models.TextChoices):
        RECEIVED = "received", _("Received")
        USED = "used", _("Taken out")
        ADJUSTED = "adjusted", _("Count corrected")

    item = models.ForeignKey(SupplyItem, on_delete=models.CASCADE, related_name="movements")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    change = models.IntegerField(help_text="Added (+) or taken out (−)")
    quantity_after = models.PositiveIntegerField()
    note = models.CharField(max_length=300, blank=True)
    purchase_request = models.ForeignKey(PurchaseRequest, null=True, blank=True, on_delete=models.SET_NULL, related_name="movements")
    by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = _("stock movement")
        verbose_name_plural = _("stock movements")

    def __str__(self):
        return f"{self.item} {self.change:+d}"
