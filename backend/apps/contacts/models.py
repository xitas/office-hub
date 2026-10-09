from django.conf import settings
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel

from .phones import normalize_phone


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


class Tag(models.Model):
    """Reusable label for contacts, created on the fly. Names are unique ignoring case."""

    name = models.CharField(max_length=50, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("tag")
        verbose_name_plural = _("tags")
        constraints = [models.UniqueConstraint(Lower("name"), name="unique_tag_name_ci")]

    def __str__(self):
        return self.name


class Contact(TimeStampedModel):
    class Status(models.TextChoices):
        NEW = "new", _("New")
        CONTACTED = "contacted", _("Contacted")
        IN_DISCUSSION = "in_discussion", _("In discussion")
        WON = "won", _("Won")
        LOST = "lost", _("Lost")

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.SET_NULL, related_name="contacts")
    job_title = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    whatsapp = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True, db_index=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name="contacts")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW, db_index=True)
    # When the current status was set (for "days in status"); the full trail is ContactStatusChange.
    status_changed_at = models.DateTimeField(default=timezone.now, db_index=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="contacts"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+", editable=False
    )
    # Digits-only international forms, kept in sync on save; used for duplicate detection.
    phone_digits = models.CharField(max_length=30, blank=True, db_index=True, editable=False)
    whatsapp_digits = models.CharField(max_length=30, blank=True, db_index=True, editable=False)

    class Meta:
        ordering = ["first_name", "last_name"]
        verbose_name = _("contact")
        verbose_name_plural = _("contacts")
        indexes = [models.Index(Lower("email"), name="contact_email_ci")]

    def __str__(self):
        return self.full_name

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def save(self, *args, **kwargs):
        self.phone_digits = normalize_phone(self.phone)
        self.whatsapp_digits = normalize_phone(self.whatsapp)
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = {*kwargs["update_fields"], "phone_digits", "whatsapp_digits"}
        super().save(*args, **kwargs)


class ContactStatusChange(models.Model):
    """One row per lead-status change (and one for the initial status), for pipeline age and reports."""

    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="status_changes")
    from_status = models.CharField(max_length=20, choices=Contact.Status.choices, blank=True)  # "" = created
    to_status = models.CharField(max_length=20, choices=Contact.Status.choices, db_index=True)
    reason = models.CharField(max_length=500, blank=True)  # optional, asked when moving to Won/Lost
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    changed_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-changed_at", "-id"]
        verbose_name = _("status change")
        verbose_name_plural = _("status changes")

    def __str__(self):
        return f"{self.contact}: {self.from_status or '-'} -> {self.to_status}"


class ContactImport(models.Model):
    """One CSV import: the uploaded rows, the chosen column mapping/options, progress and results.

    Rows are kept only until the import has run; afterwards `issues` holds what is needed for the
    results page (skipped and failed rows with their reasons and original values).
    """

    class Kind(models.TextChoices):
        CONTACTS = "contacts", _("Contacts")
        COMPANIES = "companies", _("Companies")

    class Status(models.TextChoices):
        UPLOADED = "uploaded", _("Uploaded")
        QUEUED = "queued", _("Queued")
        RUNNING = "running", _("Running")
        DONE = "done", _("Done")
        FAILED = "failed", _("Failed")

    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.CONTACTS)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPLOADED, db_index=True)
    file_name = models.CharField(max_length=255)
    headers = models.JSONField(default=list)
    rows = models.JSONField(default=list)
    mapping = models.JSONField(default=dict)  # {"<column index>": "<field key>"}
    options = models.JSONField(default=dict)
    total_rows = models.PositiveIntegerField(default=0)
    processed_rows = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    issues = models.JSONField(default=list)  # [{"line", "outcome": skipped|failed, "reason", "values"}]
    error = models.TextField(blank=True)
    background = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("import")
        verbose_name_plural = _("imports")

    def __str__(self):
        return self.file_name
