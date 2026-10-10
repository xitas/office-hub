from django.db import transaction
from django.utils.translation import gettext as _
from rest_framework import serializers

from apps.accounts.models import User
from apps.contacts.models import Company, Contact
from apps.contacts.visibility import visible_companies, visible_contacts

from .models import Task
from .rules import assignable_users, can_delete


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
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            "id", "title", "description", "assignees", "assignee_details", "due_date", "due_time",
            "priority", "priority_label", "status", "status_label", "contact", "contact_name",
            "company", "company_name", "completed_at", "is_overdue", "can_delete",
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
        return fields

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
        if attrs.get("due_time") and not attrs.get("due_date", self.instance.due_date if self.instance else None):
            raise serializers.ValidationError({"due_time": _("Set a due date first.")})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        assignees = validated_data.pop("assignees", None) or [self.context["request"].user]
        task = super().create(validated_data)
        task.assignees.set(assignees)
        return task

    @transaction.atomic
    def update(self, instance, validated_data):
        assignees = validated_data.pop("assignees", None)
        task = super().update(instance, validated_data)
        if assignees is not None:
            task.assignees.set(assignees)
        return task
