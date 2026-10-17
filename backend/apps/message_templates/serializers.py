from django.utils.translation import gettext as _
from rest_framework import serializers

from . import placeholders, rules
from .models import MessageTemplate


class MessageTemplateSerializer(serializers.ModelSerializer):
    created_by_name = serializers.CharField(source="created_by.full_name", default=None, read_only=True)
    department_name = serializers.CharField(source="department.name", default=None, read_only=True)
    archived = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    unknown_placeholders = serializers.SerializerMethodField(help_text="Placeholders in the text that don't exist.")

    class Meta:
        model = MessageTemplate
        fields = [
            "id", "name", "category", "channel", "language", "subject", "body", "sharing", "department",
            "department_name", "created_by", "created_by_name", "archived", "archived_at", "usage_count", "last_used_at",
            "can_edit", "unknown_placeholders", "created_at", "updated_at",
        ]
        read_only_fields = ["department", "created_by", "archived_at", "usage_count", "last_used_at", "created_at", "updated_at"]

    def get_archived(self, obj) -> bool:
        return obj.archived_at is not None

    def get_can_edit(self, obj) -> bool:
        return rules.can_edit(self.context["request"].user, obj)

    def get_unknown_placeholders(self, obj) -> list[str]:
        return placeholders.check(f"{obj.subject}\n{obj.body}")

    def validate_name(self, value):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError(_("This field may not be blank."))
        return value

    def validate_body(self, value):
        if not value.strip():
            raise serializers.ValidationError(_("Write the message."))
        return value.strip()

    def validate(self, attrs):
        user = self.context["request"].user
        sharing = attrs.get("sharing", self.instance.sharing if self.instance else MessageTemplate.Sharing.PERSONAL)
        changed = self.instance is None or sharing != self.instance.sharing
        if changed and not rules.can_share(user, sharing):
            raise serializers.ValidationError({"sharing": _(
                "Only admins can share templates with everyone." if sharing == MessageTemplate.Sharing.EVERYONE
                else "Only managers and admins can share templates with a department."
            )})
        if changed:
            # A department template belongs to the department of the person sharing it.
            attrs["department"] = user.department if sharing == MessageTemplate.Sharing.DEPARTMENT else None
            if sharing == MessageTemplate.Sharing.DEPARTMENT and user.department is None:
                raise serializers.ValidationError({"sharing": _("You aren't in a department.")})
        channel = attrs.get("channel", self.instance.channel if self.instance else MessageTemplate.Channel.ANY)
        if channel not in (MessageTemplate.Channel.EMAIL, MessageTemplate.Channel.ANY):
            attrs["subject"] = ""  # only emails have a subject
        return attrs


class FillSerializer(serializers.Serializer):
    """Fill for a contact, or for a vendor (its contact person and details stand in for the contact's)."""

    contact = serializers.IntegerField(required=False, allow_null=True)
    vendor = serializers.IntegerField(required=False, allow_null=True)


class PreviewSerializer(FillSerializer):
    subject = serializers.CharField(required=False, allow_blank=True, default="")
    body = serializers.CharField(allow_blank=True)
