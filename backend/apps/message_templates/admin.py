from django.contrib import admin

from .models import MessageTemplate


@admin.register(MessageTemplate)
class MessageTemplateAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "channel", "language", "sharing", "department", "created_by", "usage_count", "archived_at"]
    list_filter = ["category", "channel", "language", "sharing"]
    search_fields = ["name", "body"]
