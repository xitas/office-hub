from django.contrib import admin

from .models import Task


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ["title", "status", "priority", "due_date", "created_by"]
    list_filter = ["status", "priority"]
    search_fields = ["title"]
    raw_id_fields = ["contact", "company"]
    filter_horizontal = ["assignees"]
