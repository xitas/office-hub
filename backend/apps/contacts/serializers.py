from django.utils.translation import gettext as _
from rest_framework import serializers

from apps.accounts.models import User
from apps.core.permissions import ADMIN, has_perm

from .models import Company


class CompanySerializer(serializers.ModelSerializer):
    industry_label = serializers.CharField(source="get_industry_display", read_only=True)
    assigned_to_name = serializers.CharField(source="assigned_to.full_name", default=None, read_only=True)
    created_by_name = serializers.CharField(source="created_by.full_name", default=None, read_only=True)
    updated_by_name = serializers.CharField(source="updated_by.full_name", default=None, read_only=True)
    assigned_to = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True), required=False, allow_null=True
    )

    class Meta:
        model = Company
        fields = [
            "id", "name", "industry", "industry_label", "phone", "email", "website", "address", "city", "notes",
            "assigned_to", "assigned_to_name", "created_by_name", "updated_by_name", "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError(_("This field may not be blank."))
        return value

    def validate_city(self, value):
        return value.strip()

    def validate_website(self, value):
        return value.strip()

    def to_internal_value(self, data):
        # Accept "example.com" as a website by assuming https://.
        website = data.get("website") if hasattr(data, "get") else None
        if website and "://" not in website:
            data = data.copy()
            data["website"] = f"https://{website.strip()}"
        return super().to_internal_value(data)

    def validate_assigned_to(self, user):
        """Staff may only assign to themselves; managers to their department; admins to anyone."""
        request = self.context["request"]
        me = request.user
        if user is None or user == me:
            return user
        if not has_perm(me, "contacts", "assign_others"):
            raise serializers.ValidationError(_("You can only assign companies to yourself."))
        if me.role != ADMIN and not me.is_superuser and (not me.department_id or user.department_id != me.department_id):
            raise serializers.ValidationError(_("You can only assign companies to people in your department."))
        return user

    def create(self, validated_data):
        validated_data.setdefault("assigned_to", self.context["request"].user)
        return super().create(validated_data)
