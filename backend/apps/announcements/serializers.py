from django.utils.translation import gettext as _
from rest_framework import serializers

from apps.accounts.models import Department
from apps.core.office_time import office_today

from . import formatting, rules, services
from .models import Announcement


class AnnouncementSerializer(serializers.ModelSerializer):
    departments = serializers.PrimaryKeyRelatedField(many=True, queryset=Department.objects.all(), required=False)
    department_names = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True, default=None)
    attachments = serializers.SerializerMethodField()
    is_read = serializers.SerializerMethodField()
    expired = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    receipts = serializers.SerializerMethodField()
    remove_attachments = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)

    class Meta:
        model = Announcement
        fields = [
            "id", "title", "body", "audience", "departments", "department_names", "pinned", "expires_on", "expired",
            "created_by", "created_by_name", "published_at", "updated_at", "attachments", "is_read", "can_edit", "receipts",
            "remove_attachments",
        ]
        read_only_fields = ["created_by", "published_at", "updated_at"]
        extra_kwargs = {"body": {"max_length": 10000}}

    def get_department_names(self, obj) -> list[str]:
        return [d.name for d in obj.departments.all()]

    def get_attachments(self, obj) -> list[dict]:
        return [services.attachment_data(a) for a in obj.attachments.all()]

    def get_is_read(self, obj) -> bool:
        if hasattr(obj, "read_by_me"):
            return obj.read_by_me
        return obj.reads.filter(user=self.context["request"].user).exists()

    def get_expired(self, obj) -> bool:
        return obj.expires_on is not None and obj.expires_on < self.context.get("today", office_today())

    def get_can_edit(self, obj) -> bool:
        return rules.can_manage(self.context["request"].user, obj)

    def get_receipts(self, obj) -> dict | None:
        """{"read": n, "total": n} for the author and admins; null for everyone else."""
        if not rules.can_manage(self.context["request"].user, obj):
            return None
        counts = self.context.get("receipts")
        if counts is None:
            counts = services.receipt_counts([obj])
        return counts.get(obj.pk)

    def validate_title(self, value):
        if not value.strip():
            raise serializers.ValidationError(_("Give the announcement a title."))
        return value.strip()

    def validate_body(self, value):
        if not value.strip():
            raise serializers.ValidationError(_("Write the announcement."))
        if formatting.unsafe_links(value):
            raise serializers.ValidationError(_("Links must start with http://, https:// or mailto:."))
        return value.strip()

    def validate_expires_on(self, value):
        unchanged = self.instance is not None and self.instance.expires_on == value
        if value is not None and value < office_today() and not unchanged:
            raise serializers.ValidationError(_("The expiry date can't be in the past."))
        return value

    def validate(self, attrs):
        user = self.context["request"].user
        audience = attrs.get("audience", self.instance.audience if self.instance else Announcement.Audience.EVERYONE)
        if "departments" in attrs:
            departments = attrs["departments"]
        else:
            departments = list(self.instance.departments.all()) if self.instance else []
        if audience == Announcement.Audience.EVERYONE:
            if not rules.is_admin(user):
                raise serializers.ValidationError({"audience": [_("Only admins can post to everyone. Choose your department.")]})
            attrs["departments"] = []
        else:
            if not departments:
                raise serializers.ValidationError({"departments": [_("Choose at least one department.")]})
            if not rules.is_admin(user) and {d.pk for d in departments} != {user.department_id}:
                raise serializers.ValidationError({"departments": [_("Managers post to their own department only.")]})
            attrs["departments"] = departments
        attrs["audience"] = audience
        return attrs
