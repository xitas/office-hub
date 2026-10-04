from django.contrib import admin

from .models import Notification, NotificationPreference


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["created_at", "recipient", "type", "title", "is_read"]
    list_filter = ["type", "is_read"]


admin.site.register(NotificationPreference)
