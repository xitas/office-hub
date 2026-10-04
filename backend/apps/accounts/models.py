from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class Department(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="managed_departments"
    )

    class Meta:
        ordering = ["name"]
        verbose_name = _("department")
        verbose_name_plural = _("departments")

    def __str__(self):
        return self.name


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("Email is required")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_superuser", True)
        extra.setdefault("role", User.Role.ADMIN)
        return self._create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        ADMIN = "admin", _("Admin")
        MANAGER = "manager", _("Manager")
        STAFF = "staff", _("Staff")

    class Theme(models.TextChoices):
        LIGHT = "light", _("Light")
        DARK = "dark", _("Dark")
        SYSTEM = "system", _("System")

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=30, blank=True)
    job_title = models.CharField(max_length=100, blank=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.STAFF, db_index=True)
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.SET_NULL, related_name="members")
    avatar = models.ImageField(upload_to="avatars/", null=True, blank=True)
    language = models.CharField(max_length=5, choices=settings.LANGUAGES, default="en")
    theme = models.CharField(max_length=10, choices=Theme.choices, default=Theme.SYSTEM)
    is_active = models.BooleanField(default=True)

    # Two-factor auth (TOTP). The secret is set during setup and only trusted once enabled.
    totp_secret = models.CharField(max_length=64, blank=True)
    two_factor_enabled = models.BooleanField(default=False)
    backup_codes = models.JSONField(default=list, blank=True)  # hashed codes

    date_joined = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        ordering = ["full_name"]
        verbose_name = _("user")
        verbose_name_plural = _("users")

    def __str__(self):
        return self.full_name or self.email

    @property
    def is_staff(self):
        """Django admin site access: admins only. (Unrelated to the "staff" CRM role.)"""
        return self.role == self.Role.ADMIN or self.is_superuser

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN or self.is_superuser

    @property
    def is_manager(self):
        return self.role == self.Role.MANAGER
