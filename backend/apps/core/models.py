from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db import models
from django.utils.translation import gettext_lazy as _


class TimeStampedModel(models.Model):
    """Base for all domain tables: creation/update timestamps and creator."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        editable=False,
    )

    class Meta:
        abstract = True


class OrganizationSettings(models.Model):
    """Singleton (pk=1) holding office-wide preferences."""

    class DateFormat(models.TextChoices):
        DMY = "DD/MM/YYYY", "DD/MM/YYYY"
        MDY = "MM/DD/YYYY", "MM/DD/YYYY"
        YMD = "YYYY-MM-DD", "YYYY-MM-DD"
        D_MON_Y = "DD MMM YYYY", "DD MMM YYYY"

    class WeekStart(models.IntegerChoices):
        SUNDAY = 0, "Sunday"
        MONDAY = 1, "Monday"
        SATURDAY = 6, "Saturday"

    org_name = models.CharField(max_length=150, default="Our Office")
    currency = models.CharField(max_length=3, default="PKR")
    date_format = models.CharField(max_length=20, choices=DateFormat.choices, default=DateFormat.DMY)
    timezone = models.CharField(max_length=64, default="Asia/Karachi")
    week_start = models.PositiveSmallIntegerField(choices=WeekStart.choices, default=WeekStart.MONDAY)
    default_language = models.CharField(max_length=5, choices=settings.LANGUAGES, default="en")
    # Admin-controlled switches for staff (managers and admins always have these).
    staff_can_import_contacts = models.BooleanField(default=True)
    staff_can_export_contacts = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("organization settings")
        verbose_name_plural = _("organization settings")

    def __str__(self):
        return self.org_name

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete(self.CACHE_KEY)

    CACHE_KEY = "org-settings"

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @classmethod
    def cached(cls):
        """Read-mostly copy for hot paths (permission checks); refreshed whenever the settings are saved."""
        obj = cache.get(cls.CACHE_KEY)
        if obj is None:
            obj = cls.get_solo()
            cache.set(cls.CACHE_KEY, obj, timeout=300)
        return obj


class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = "create", _("Created")
        UPDATE = "update", _("Updated")
        DELETE = "delete", _("Deleted")
        LOGIN = "login", _("Signed in")
        LOGIN_FAILED = "login_failed", _("Failed sign-in")
        LOGOUT = "logout", _("Signed out")
        SECURITY = "security", _("Security change")
        IMPORT = "import", _("Imported")
        EXPORT = "export", _("Exported")
        OTHER = "other", _("Other")

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_entries"
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    object_id = models.CharField(max_length=64, blank=True)
    object_repr = models.CharField(max_length=255, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    # Stored as an untranslated English message id; translated when read.
    description = models.CharField(max_length=255, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = _("audit entry")
        verbose_name_plural = _("audit entries")
        indexes = [
            models.Index(fields=["actor", "-timestamp"]),
            models.Index(fields=["content_type", "object_id"]),
        ]

    def __str__(self):
        return f"{self.actor} {self.action} {self.object_repr}"
