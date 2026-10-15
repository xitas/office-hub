from django.utils.translation import gettext as _
from rest_framework import serializers

from apps.core.office_time import office_today

from . import rules
from .models import LeaveRequest, LeaveType


class LeaveTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveType
        fields = ["id", "name", "name_ur", "days_per_year", "paid", "allow_half_days", "is_active", "position"]
        extra_kwargs = {"days_per_year": {"min_value": 0, "max_value": 365}}

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError(_("Give the leave type a name."))
        return value.strip()

    def validate_days_per_year(self, value):
        if value is not None and value % 1 not in (0, 0.5):
            raise serializers.ValidationError(_("Use whole or half days."))
        return value


class LeaveRequestSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.full_name", read_only=True)
    department_name = serializers.CharField(source="user.department.name", read_only=True, default=None)
    type_name = serializers.CharField(source="leave_type.name", read_only=True)
    type_name_ur = serializers.CharField(source="leave_type.name_ur", read_only=True)
    decided_by_name = serializers.CharField(source="decided_by.full_name", read_only=True, default=None)
    can_cancel = serializers.SerializerMethodField()
    can_decide = serializers.SerializerMethodField()

    class Meta:
        model = LeaveRequest
        fields = [
            "id", "user", "user_name", "department_name", "leave_type", "type_name", "type_name_ur", "start_date", "end_date",
            "half_day", "days", "reason", "status", "decided_by_name", "decided_at", "decision_note", "can_cancel", "can_decide",
            "created_at",
        ]
        read_only_fields = fields

    def get_can_cancel(self, obj) -> bool:
        return rules.can_cancel(self.context["request"].user, obj, self.context.get("today") or office_today())

    def get_can_decide(self, obj) -> bool:
        return rules.can_decide(self.context["request"].user, obj)


class TeamLeaveSerializer(serializers.ModelSerializer):
    """Colleagues' approved leave: who and when, never the reason."""

    user_name = serializers.CharField(source="user.full_name", read_only=True)
    type_name = serializers.CharField(source="leave_type.name", read_only=True)
    type_name_ur = serializers.CharField(source="leave_type.name_ur", read_only=True)

    class Meta:
        model = LeaveRequest
        fields = ["id", "user", "user_name", "type_name", "type_name_ur", "start_date", "end_date", "half_day", "days"]
        read_only_fields = fields


class LeaveInputSerializer(serializers.Serializer):
    leave_type = serializers.PrimaryKeyRelatedField(queryset=LeaveType.objects.all())
    start_date = serializers.DateField()
    end_date = serializers.DateField(required=False)
    half_day = serializers.ChoiceField(choices=LeaveRequest.HalfDay.choices, required=False, allow_blank=True, default="")
    reason = serializers.CharField(required=False, allow_blank=True, max_length=1000, default="")

    def validate(self, attrs):
        attrs.setdefault("end_date", attrs["start_date"])
        return attrs


class LeaveDecisionSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    note = serializers.CharField(required=False, allow_blank=True, max_length=300, default="")


class AllowanceSerializer(serializers.Serializer):
    user = serializers.IntegerField()
    leave_type = serializers.PrimaryKeyRelatedField(queryset=LeaveType.objects.all())
    year = serializers.IntegerField(min_value=2000, max_value=2100)
    allowance = serializers.DecimalField(max_digits=5, decimal_places=1, min_value=0, max_value=365)
    note = serializers.CharField(required=False, allow_blank=True, max_length=200, default="")

    def validate_allowance(self, value):
        if value % 1 not in (0, 0.5):
            raise serializers.ValidationError(_("Use whole or half days."))
        return value
