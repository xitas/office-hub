from django.contrib import admin

from .models import TimelineEntry


@admin.register(TimelineEntry)
class TimelineEntryAdmin(admin.ModelAdmin):
    list_display = ["kind", "contact", "company", "occurred_at", "created_by"]
    list_filter = ["kind"]
    search_fields = ["summary"]
    raw_id_fields = ["contact", "company", "created_by", "updated_by"]
