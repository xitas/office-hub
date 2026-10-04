from django.utils.translation import gettext as _
from rest_framework import serializers

from .audit import model_label, translated_description
from .models import AuditLog, OrganizationSettings


class OrganizationSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationSettings
        fields = ["org_name", "currency", "date_format", "timezone", "week_start", "default_language", "updated_at"]
        read_only_fields = ["updated_at"]

    def validate_currency(self, value):
        value = value.upper()
        if len(value) != 3 or not value.isalpha():
            raise serializers.ValidationError(_("Use a 3-letter ISO currency code, e.g. PKR."))
        return value

    def validate_timezone(self, value):
        from zoneinfo import available_timezones

        if value not in available_timezones():
            raise serializers.ValidationError(_("Unknown timezone."))
        return value


class AuditLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.full_name", default=None, read_only=True)
    model = serializers.SerializerMethodField()
    model_label = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    action_label = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = AuditLog
        fields = [
            "id", "actor", "actor_name", "action", "action_label", "model", "model_label", "object_id",
            "object_repr", "changes", "description", "ip", "timestamp",
        ]

    def get_model(self, obj) -> str | None:
        return obj.content_type.model if obj.content_type_id else None

    def get_model_label(self, obj) -> str | None:
        return model_label(obj.content_type)

    def get_description(self, obj) -> str:
        return translated_description(obj)
