from django.contrib import admin

from .models import Announcement, AnnouncementAttachment


class AttachmentInline(admin.TabularInline):
    model = AnnouncementAttachment
    extra = 0
    fields = ["original_name", "size", "kind", "created_at"]
    readonly_fields = fields


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ["title", "audience", "pinned", "expires_on", "created_by", "published_at"]
    list_filter = ["audience", "pinned"]
    search_fields = ["title", "body"]
    filter_horizontal = ["departments"]
    inlines = [AttachmentInline]
