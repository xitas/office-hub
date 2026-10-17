from django.contrib import admin

from .models import Visit


@admin.register(Visit)
class VisitAdmin(admin.ModelAdmin):
    list_display = ["title", "assigned_to", "start", "status", "purpose"]
    list_filter = ["status", "purpose"]
    raw_id_fields = ["contact", "company", "vendor", "assigned_to", "task", "decided_by", "closed_by", "created_by"]
