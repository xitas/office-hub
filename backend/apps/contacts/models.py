from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class Company(TimeStampedModel):
    class Industry(models.TextChoices):
        RETAIL = "retail", _("Retail")
        MANUFACTURING = "manufacturing", _("Manufacturing")
        SERVICES = "services", _("Professional services")
        CONSTRUCTION = "construction", _("Construction")
        HEALTHCARE = "healthcare", _("Healthcare")
        EDUCATION = "education", _("Education")
        TECHNOLOGY = "technology", _("Technology")
        FINANCE = "finance", _("Finance")
        REAL_ESTATE = "real_estate", _("Real estate")
        LOGISTICS = "logistics", _("Logistics")
        HOSPITALITY = "hospitality", _("Hospitality")
        GOVERNMENT = "government", _("Government")
        OTHER = "other", _("Other")

    name = models.CharField(max_length=200, db_index=True)
    industry = models.CharField(max_length=30, choices=Industry.choices, blank=True, db_index=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True, db_index=True)
    notes = models.TextField(blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="companies"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", editable=False
    )

    class Meta:
        ordering = ["name"]
        verbose_name = _("company")
        verbose_name_plural = _("companies")

    def __str__(self):
        return self.name
