from django.utils.translation import gettext as _
from rest_framework import serializers

from .audit import model_label, translated_description
from .models import AuditLog, OrganizationSettings


class OrganizationSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationSettings
        fields = [
            "org_name", "currency", "date_format", "timezone", "week_start", "time_format", "default_language",
            "staff_can_import_contacts", "staff_can_export_contacts",
            "office_opens", "office_closes", "booking_max_minutes", "booking_horizon_days", "working_days",
            "late_after_minutes", "attendance_reminders", "visits_need_approval", "updated_at",
        ]
        extra_kwargs = {
            "booking_max_minutes": {"min_value": 15, "max_value": 24 * 60},
            "booking_horizon_days": {"min_value": 1, "max_value": 730},
            "late_after_minutes": {"min_value": 0, "max_value": 240},
        }
        read_only_fields = ["updated_at"]

    def validate_currency(self, value):
        value = value.upper()
        if len(value) != 3 or not value.isalpha():
            raise serializers.ValidationError(_("Use a 3-letter ISO currency code, e.g. PKR."))
        return value

    def validate(self, attrs):
        opens = attrs.get("office_opens", getattr(self.instance, "office_opens", None))
        closes = attrs.get("office_closes", getattr(self.instance, "office_closes", None))
        if opens and closes:
            if closes <= opens:
                raise serializers.ValidationError({"office_closes": [_("The office must close after it opens.")]})
            if opens.minute % 15 or closes.minute % 15 or opens.second or closes.second:
                raise serializers.ValidationError({"office_opens": [_("Use quarter hours, e.g. 09:00 or 17:30.")]})
        if "booking_max_minutes" in attrs and attrs["booking_max_minutes"] % 15:
            raise serializers.ValidationError({"booking_max_minutes": [_("Use a multiple of 15 minutes.")]})
        return attrs

    def validate_working_days(self, value):
        if not isinstance(value, list) or not value or any(not isinstance(d, int) or d < 0 or d > 6 for d in value):
            raise serializers.ValidationError(_("Choose at least one working day."))
        return sorted(set(value))

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
