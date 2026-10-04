from django.contrib import admin

from .models import Department, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    """Read-mostly view; users are managed through the CRM's admin screens (passwords via the API)."""

    ordering = ["full_name"]
    list_display = ["email", "full_name", "role", "department", "is_active", "two_factor_enabled", "last_login"]
    list_filter = ["role", "department", "is_active", "two_factor_enabled"]
    search_fields = ["email", "full_name", "phone"]
    fields = [
        "email", "full_name", "phone", "job_title", "avatar", "language", "theme",
        "role", "department", "is_active", "is_superuser", "two_factor_enabled", "last_login", "date_joined",
    ]
    readonly_fields = ["last_login", "date_joined", "two_factor_enabled"]

    def has_add_permission(self, request):
        return False


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ["name", "manager", "created_at"]
    search_fields = ["name"]
