from django.urls import reverse
from django.utils.translation import gettext as _
from rest_framework import serializers

from .collab import can_change_comment, can_delete_attachment, can_delete_comment
from .models import ChecklistItem, TaskAttachment, TaskComment


class ChecklistItemSerializer(serializers.ModelSerializer):
    done_by_name = serializers.CharField(source="done_by.full_name", default=None, read_only=True)

    class Meta:
        model = ChecklistItem
        fields = ["id", "text", "done", "position", "done_by_name", "done_at", "created_at"]
        read_only_fields = ["position", "done_at", "created_at"]

    def validate_text(self, value):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError(_("This field may not be blank."))
        return value


class AttachmentSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(source="uploaded_by.full_name", default=None, read_only=True)
    download_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = TaskAttachment
        fields = [
            "id", "original_name", "size", "content_type", "kind", "comment", "uploaded_by_name",
            "created_at", "download_url", "thumbnail_url", "can_delete",
        ]

    # Relative API paths: the frontend fetches them with the user's token (they are not public links).
    def get_download_url(self, obj) -> str:
        return reverse("task-attachment-download", args=[obj.pk]).removeprefix("/api/v1")

    def get_thumbnail_url(self, obj) -> str | None:
        return reverse("task-attachment-thumbnail", args=[obj.pk]).removeprefix("/api/v1") if obj.thumbnail else None

    def get_can_delete(self, obj) -> bool:
        return can_delete_attachment(self.context["request"].user, obj)


class CommentSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.full_name", default=None, read_only=True)
    author_avatar = serializers.ImageField(source="author.avatar", default=None, read_only=True)
    attachments = AttachmentSerializer(many=True, read_only=True)
    can_edit = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()
    body = serializers.CharField(max_length=10_000, allow_blank=True, required=False, trim_whitespace=True)

    class Meta:
        model = TaskComment
        fields = ["id", "body", "author", "author_name", "author_avatar", "created_at", "edited_at", "attachments", "can_edit", "can_delete"]
        read_only_fields = ["author", "created_at", "edited_at"]

    def get_can_edit(self, obj) -> bool:
        return can_change_comment(self.context["request"].user, obj)

    def get_can_delete(self, obj) -> bool:
        return can_delete_comment(self.context["request"].user, obj)
