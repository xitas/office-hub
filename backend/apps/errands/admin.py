from django.contrib import admin

from .models import Errand


@admin.register(Errand)
class ErrandAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "status", "assigned_to", "requested_by", "due_at")
    list_filter = ("kind", "status")
    search_fields = ("title", "place_name", "reference")
