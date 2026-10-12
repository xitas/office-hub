from django.contrib import admin

from .models import Conversation, Membership, Message


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    raw_id_fields = ["user"]


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ["__str__", "kind", "channel_type", "is_private", "is_default", "department", "archived_at"]
    list_filter = ["kind", "channel_type", "is_private", "is_default"]
    inlines = [MembershipInline]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ["id", "conversation", "author", "created_at", "edited_at", "deleted_at"]
    raw_id_fields = ["conversation", "author", "reply_to"]
