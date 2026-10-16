from django.utils.translation import gettext as _
from rest_framework import serializers

from apps.accounts.models import Department, User

from . import rules
from .models import GoalUpdate, WeeklyGoal


class WeeklyGoalSerializer(serializers.ModelSerializer):
    department = serializers.PrimaryKeyRelatedField(queryset=Department.objects.all(), allow_null=True, required=False)
    owner = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), allow_null=True, required=False)
    department_name = serializers.CharField(source="department.name", read_only=True, default=None)
    owner_name = serializers.CharField(source="owner.full_name", read_only=True, default=None)
    done = serializers.BooleanField(read_only=True)
    can_edit = serializers.SerializerMethodField()
    can_record = serializers.SerializerMethodField()

    class Meta:
        model = WeeklyGoal
        fields = [
            "id", "week_start", "department", "department_name", "title", "description", "owner", "owner_name",
            "target", "unit", "current", "done", "position", "carried_from", "completed_at", "can_edit", "can_record",
            "updated_at",
        ]
        read_only_fields = ["current", "carried_from", "completed_at", "updated_at"]
        extra_kwargs = {"target": {"min_value": 1, "max_value": 1_000_000}}

    def validate_title(self, value):
        if not value.strip():
            raise serializers.ValidationError(_("Give the goal a title."))
        return value.strip()

    def get_can_edit(self, obj) -> bool:
        return rules.can_manage(self.context["request"].user, obj)

    def get_can_record(self, obj) -> bool:
        return rules.can_record(self.context["request"].user, obj)


class ProgressSerializer(serializers.Serializer):
    """Either ``value`` (the new total) or ``add`` (a change, negative to correct)."""

    value = serializers.IntegerField(min_value=0, required=False, allow_null=True, default=None)
    add = serializers.IntegerField(required=False, allow_null=True, default=None)
    note = serializers.CharField(required=False, allow_blank=True, max_length=300, default="")

    def validate(self, attrs):
        if (attrs["value"] is None) == (attrs["add"] is None):
            raise serializers.ValidationError({"value": [_("Give the new progress or the change.")]})
        return attrs


class GoalUpdateSerializer(serializers.ModelSerializer):
    by_name = serializers.CharField(source="by.full_name", read_only=True, default=None)

    class Meta:
        model = GoalUpdate
        fields = ["id", "before", "after", "note", "by_name", "created_at"]
        read_only_fields = fields


class CarryOverSerializer(serializers.Serializer):
    week_start = serializers.DateField()
    department = serializers.IntegerField(required=False, allow_null=True, default=None)
    all_departments = serializers.BooleanField(required=False, default=False)
