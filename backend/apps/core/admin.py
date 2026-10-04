from django.contrib import admin

from .models import AuditLog, OrganizationSettings


@admin.register(OrganizationSettings)
class OrganizationSettingsAdmin(admin.ModelAdmin):
    list_display = ["org_name", "currency", "date_format", "timezone"]


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["timestamp", "actor", "action", "content_type", "object_repr", "ip"]
    list_filter = ["action", "content_type"]
    search_fields = ["object_repr", "description", "actor__email"]
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
