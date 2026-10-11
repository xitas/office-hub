from django.db import transaction
from django.utils.translation import gettext as _
from rest_framework import serializers

from apps.accounts.models import User
from apps.contacts.models import Company, Contact
from apps.contacts.visibility import visible_companies, visible_contacts

from apps.timeline.models import TimelineEntry

from . import schedule
from .models import Task
from .rules import assignable_users, can_delete


class RecurrenceSerializer(serializers.Serializer):
    """How a task repeats. The task's due date is the first occurrence."""

    frequency = serializers.ChoiceField(choices=["daily", "weekly", "monthly"])
    interval = serializers.IntegerField(min_value=1, max_value=99, default=1)
    weekdays = serializers.ListField(child=serializers.IntegerField(min_value=0, max_value=6), required=False, max_length=7)
    monthly_mode = serializers.ChoiceField(choices=["day", "weekday"], default="day")
    month_day = serializers.IntegerField(min_value=1, max_value=31, required=False, allow_null=True)
    month_week = serializers.ChoiceField(choices=[1, 2, 3, 4, -1], required=False, allow_null=True)
    month_weekday = serializers.IntegerField(min_value=0, max_value=6, required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)
    count = serializers.IntegerField(min_value=1, max_value=500, required=False, allow_null=True)

    def validate(self, attrs):
        if attrs["frequency"] == "weekly":
            attrs["weekdays"] = sorted(set(attrs.get("weekdays") or []))
            if not attrs["weekdays"]:
                raise serializers.ValidationError({"weekdays": [_("Choose at least one day of the week.")]})
        else:
            attrs["weekdays"] = []
        if attrs["frequency"] == "monthly" and attrs["monthly_mode"] == "weekday":
            if attrs.get("month_week") is None or attrs.get("month_weekday") is None:
                raise serializers.ValidationError({"month_week": [_("Choose which weekday of the month.")]})
        return attrs


def series_data(series) -> dict | None:
    if series is None:
        return None
    return {
        "id": series.pk,
        "frequency": series.frequency,
        "interval": series.interval,
        "weekdays": series.weekdays,
        "monthly_mode": series.monthly_mode,
        "month_day": series.month_day,
        "month_week": series.month_week,
        "month_weekday": series.month_weekday,
        "start_date": series.start_date,
        "end_date": series.end_date,
        "count": series.count,
        "occurrences_created": series.occurrences_created,
        "active": series.active,
    }


class AssigneeSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "full_name", "avatar"]


class TaskSerializer(serializers.ModelSerializer):
    assignees = serializers.PrimaryKeyRelatedField(
        many=True, queryset=User.objects.filter(is_active=True), required=False
    )
    assignee_details = AssigneeSerializer(source="assignees", many=True, read_only=True)
    contact = serializers.PrimaryKeyRelatedField(queryset=Contact.objects.none(), required=False, allow_null=True)
    company = serializers.PrimaryKeyRelatedField(queryset=Company.objects.none(), required=False, allow_null=True)
    contact_name = serializers.CharField(source="contact.full_name", default=None, read_only=True)
    company_name = serializers.CharField(source="company.name", default=None, read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    priority_label = serializers.CharField(source="get_priority_display", read_only=True)
    created_by_name = serializers.CharField(source="created_by.full_name", default=None, read_only=True)
    updated_by_name = serializers.CharField(source="updated_by.full_name", default=None, read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    checklist_total = serializers.IntegerField(read_only=True, default=0)
    checklist_done = serializers.IntegerField(read_only=True, default=0)
    comment_count = serializers.IntegerField(read_only=True, default=0)
    can_delete = serializers.SerializerMethodField()
    recurrence = RecurrenceSerializer(required=False, allow_null=True, write_only=True)
    repeat = serializers.SerializerMethodField(help_text="The task's repeat rule, or null.")
    # "this" (default): change only this occurrence. "future": also the series and later occurrences.
    scope = serializers.ChoiceField(choices=["this", "future"], default="this", write_only=True)
    follow_up_of = serializers.PrimaryKeyRelatedField(queryset=TimelineEntry.objects.none(), required=False, allow_null=True)

    class Meta:
        model = Task
        fields = [
            "id", "title", "description", "assignees", "assignee_details", "due_date", "due_time",
            "priority", "priority_label", "status", "status_label", "contact", "contact_name",
            "company", "company_name", "completed_at", "is_overdue", "can_delete",
            "checklist_total", "checklist_done", "comment_count", "recurrence", "repeat", "scope", "follow_up_of",
            "created_by", "created_by_name", "updated_by_name", "created_at", "updated_at",
        ]
        read_only_fields = ["completed_at", "created_by", "created_at", "updated_at"]

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            # Links only to records this user can see; others look like unknown ids.
            fields["contact"].queryset = visible_contacts(request.user)
            fields["company"].queryset = visible_companies(request.user)
            from apps.timeline.views import visible_entries

            fields["follow_up_of"].queryset = visible_entries(request.user)
        return fields

    def get_repeat(self, task) -> dict | None:
        return series_data(task.series)

    def get_can_delete(self, task) -> bool:
        return can_delete(self.context["request"].user, task)

    def validate_title(self, value):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError(_("This field may not be blank."))
        return value

    def validate_assignees(self, users):
        if not users:
            raise serializers.ValidationError(_("Assign at least one person."))
        me = self.context["request"].user
        # Only people being added are checked, so editing a task never fails over existing assignees.
        current = set(self.instance.assignees.values_list("pk", flat=True)) if self.instance else set()
        added = [u for u in users if u.pk not in current]
        allowed = set(assignable_users(me, User.objects.filter(pk__in=[u.pk for u in added])).values_list("pk", flat=True))
        refused = [u for u in added if u.pk not in allowed]
        if refused:
            raise serializers.ValidationError(
                _("You can only assign tasks to yourself and people in your department.")
                if me.department_id else _("You can only assign tasks to yourself.")
            )
        return list(dict.fromkeys(users))

    def validate(self, attrs):
        contact = attrs.get("contact", self.instance.contact if self.instance else None)
        company = attrs.get("company", self.instance.company if self.instance else None)
        if contact and company:
            raise serializers.ValidationError({"company": _("Link the task to a contact or a company, not both.")})
        due_date = attrs.get("due_date", self.instance.due_date if self.instance else None)
        if attrs.get("due_time") and not due_date:
            raise serializers.ValidationError({"due_time": _("Set a due date first.")})
        recurrence = attrs.get("recurrence")
        if recurrence:
            if not due_date:
                raise serializers.ValidationError({"recurrence": [_("A repeating task needs a due date (its first occurrence).")]})
            if recurrence.get("end_date") and recurrence["end_date"] < due_date:
                raise serializers.ValidationError({"recurrence": [_("The end date is before the first occurrence.")]})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        user = self.context["request"].user
        assignees = validated_data.pop("assignees", None) or [user]
        recurrence = validated_data.pop("recurrence", None)
        validated_data.pop("scope", None)
        task = super().create(validated_data)
        task.assignees.set(assignees)
        if recurrence:
            schedule.start_series(task, recurrence, user)
        return task

    @transaction.atomic
    def update(self, instance, validated_data):
        user = self.context["request"].user
        assignees = validated_data.pop("assignees", None)
        scope = validated_data.pop("scope", "this")
        has_rule = "recurrence" in validated_data
        recurrence = validated_data.pop("recurrence", None)
        changed = set(validated_data) | ({"assignees"} if assignees is not None else set())
        task = super().update(instance, validated_data)
        if assignees is not None:
            task.assignees.set(assignees)
        series = task.series
        if has_rule:
            if recurrence is None:
                if series:
                    schedule.stop_series(series)  # existing occurrences stay; no new ones are made
            elif series is None or not series.active:
                schedule.start_series(task, recurrence, user)
            else:
                schedule.update_rule(series, task, recurrence)  # a rule change applies from this occurrence on
                schedule.update_template(series, task)
        elif scope == "future" and series:
            schedule.update_template(series, task)
            later = series.occurrences.filter(due_date__gt=task.due_date).exclude(status=Task.Status.DONE)
            fields = [f for f in ("title", "description", "priority", "due_time", "contact", "company") if f in changed]
            for other in later:
                for f in fields:
                    setattr(other, f, getattr(task, f))
                other.save()
                if "assignees" in changed:
                    other.assignees.set(task.assignees.all())
        return task
