from django.db import transaction
from django.utils.translation import gettext as _
from rest_framework import serializers

from apps.accounts.models import User
from apps.core.permissions import ADMIN, has_perm

from .duplicates import find_duplicates
from .models import Company, Contact, Tag
from .visibility import visible_companies

MAX_TAGS = 20


class AssignmentMixin:
    """Shared assignment rules: staff -> themselves, managers -> their department, admins -> anyone.

    New records default to the creating user.
    """

    def validate_assigned_to(self, user):
        me = self.context["request"].user
        if user is None or user == me:
            return user
        if not has_perm(me, "contacts", "assign_others"):
            raise serializers.ValidationError(_("You can only assign this to yourself."))
        if me.role != ADMIN and not me.is_superuser and (not me.department_id or user.department_id != me.department_id):
            raise serializers.ValidationError(_("You can only assign this to people in your department."))
        return user

    def create(self, validated_data):
        validated_data.setdefault("assigned_to", self.context["request"].user)
        return super().create(validated_data)


def _assignable_users():
    return User.objects.filter(is_active=True)


class CompanySerializer(AssignmentMixin, serializers.ModelSerializer):
    industry_label = serializers.CharField(source="get_industry_display", read_only=True)
    assigned_to_name = serializers.CharField(source="assigned_to.full_name", default=None, read_only=True)
    created_by_name = serializers.CharField(source="created_by.full_name", default=None, read_only=True)
    updated_by_name = serializers.CharField(source="updated_by.full_name", default=None, read_only=True)
    assigned_to = serializers.PrimaryKeyRelatedField(queryset=_assignable_users(), required=False, allow_null=True)

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


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ["id", "name"]


class ContactSerializer(AssignmentMixin, serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    company = serializers.PrimaryKeyRelatedField(queryset=Company.objects.all(), required=False, allow_null=True)
    company_name = serializers.CharField(source="company.name", default=None, read_only=True)
    assigned_to = serializers.PrimaryKeyRelatedField(queryset=_assignable_users(), required=False, allow_null=True)
    assigned_to_name = serializers.CharField(source="assigned_to.full_name", default=None, read_only=True)
    created_by_name = serializers.CharField(source="created_by.full_name", default=None, read_only=True)
    updated_by_name = serializers.CharField(source="updated_by.full_name", default=None, read_only=True)
    tags = serializers.ListField(
        child=serializers.CharField(max_length=50), required=False, max_length=MAX_TAGS, write_only=True
    )
    tag_names = serializers.SerializerMethodField()

    class Meta:
        model = Contact
        fields = [
            "id", "first_name", "last_name", "full_name", "company", "company_name", "job_title", "phone",
            "whatsapp", "email", "address", "city", "tags", "tag_names", "status", "status_label",
            "assigned_to", "assigned_to_name", "created_by_name", "updated_by_name", "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_tag_names(self, obj) -> list[str]:
        return [t.name for t in obj.tags.all()]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["tags"] = data.pop("tag_names")
        return data

    def validate_first_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError(_("This field may not be blank."))
        return value

    def validate_last_name(self, value):
        return value.strip()

    def validate_city(self, value):
        return value.strip()

    def validate_company(self, company):
        """A contact can only be linked to a company the user can see."""
        if company is not None and not visible_companies(self.context["request"].user).filter(pk=company.pk).exists():
            raise serializers.ValidationError(_("Company not found."))
        return company

    def validate_tags(self, names):
        cleaned, seen = [], set()
        for name in names:
            name = " ".join(name.split())
            if name and name.casefold() not in seen:
                seen.add(name.casefold())
                cleaned.append(name)
        return cleaned

    @staticmethod
    def _resolve_tags(names):
        """Existing tags are matched ignoring case; new ones are created on the fly."""
        tags = []
        for name in names:
            tag = Tag.objects.filter(name__iexact=name).first() or Tag.objects.create(name=name)
            tags.append(tag)
        return tags

    @transaction.atomic
    def create(self, validated_data):
        names = validated_data.pop("tags", None)
        contact = super().create(validated_data)
        if names:
            contact.tags.set(self._resolve_tags(names))
        return contact

    @transaction.atomic
    def update(self, instance, validated_data):
        names = validated_data.pop("tags", None)
        contact = super().update(instance, validated_data)
        if names is not None:
            contact.tags.set(self._resolve_tags(names))
        return contact

    def duplicates(self, instance) -> list[dict]:
        return find_duplicates(
            self.context["request"].user,
            phone=instance.phone,
            whatsapp=instance.whatsapp,
            email=instance.email,
            exclude_id=instance.pk,
        )
