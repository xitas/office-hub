from datetime import timedelta

from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.contacts.models import Company, Contact
from apps.contacts.visibility import visible_companies, visible_contacts
from apps.core.permissions import ADMIN, MANAGER

from . import registry
from .models import TimelineEntry

# Clocks differ a little between devices; anything later than this counts as "in the future".
FUTURE_LEEWAY = timedelta(minutes=5)


def can_modify(user, entry) -> bool:
    """Edit/delete: the author, a manager of the author's department, or an admin.
    (The caller has already checked that the user can see the entry's contact/company.)"""
    if user.role == ADMIN or user.is_superuser:
        return True
    if entry.created_by_id == user.pk:
        return True
    author = entry.created_by
    return bool(
        user.role == MANAGER and user.department_id and author is not None and author.department_id == user.department_id
    )


class TimelineEntrySerializer(serializers.ModelSerializer):
    """Create/edit a stored entry. Responses use the same shape as automatic entries (see registry.auto_entry)."""

    kind = serializers.CharField(max_length=40)
    contact = serializers.PrimaryKeyRelatedField(queryset=Contact.objects.none(), required=False, allow_null=True)
    company = serializers.PrimaryKeyRelatedField(queryset=Company.objects.none(), required=False, allow_null=True)
    summary = serializers.CharField(max_length=5000, required=False, allow_blank=True)
    details = serializers.JSONField(required=False)

    class Meta:
        model = TimelineEntry
        fields = ["kind", "contact", "company", "summary", "details", "occurred_at", "follow_up_on"]

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:  # (schema generation runs anonymously)
            # Entries can only be added to records the user can see; others look like unknown ids.
            fields["contact"].queryset = visible_contacts(request.user)
            fields["company"].queryset = visible_companies(request.user)
        return fields

    def validate_kind(self, value):
        if self.instance is not None and value != self.instance.kind:
            raise serializers.ValidationError(_("The type of an entry cannot be changed."))
        if registry.get_type(value) is None:
            raise serializers.ValidationError(_("Unknown entry type."))
        return value

    def validate_occurred_at(self, value):
        if value > timezone.now() + FUTURE_LEEWAY:
            raise serializers.ValidationError(_("The date cannot be in the future."))
        return value

    def validate(self, attrs):
        instance = self.instance
        if instance is not None:
            # The record an entry belongs to is fixed once it is logged.
            for field in ("contact", "company"):
                if field in attrs and attrs[field] != getattr(instance, field):
                    raise serializers.ValidationError({field: _("An entry cannot be moved to another record.")})
            kind = instance.kind
        else:
            kind = attrs.get("kind")
            if bool(attrs.get("contact")) == bool(attrs.get("company")):
                raise serializers.ValidationError(_("Choose either a contact or a company."))
        entry_type = registry.get_type(kind)

        summary = attrs.get("summary", instance.summary if instance else "").strip()
        if "summary" in attrs:
            attrs["summary"] = summary
        if entry_type.requires_summary and not summary:
            raise serializers.ValidationError({"summary": _("Please write something.")})

        if "details" in attrs or instance is None:
            details = attrs.get("details") or {}
            if entry_type.details_serializer is None:
                attrs["details"] = {}
            else:
                checker = entry_type.details_serializer(data=details)
                if not checker.is_valid():
                    raise serializers.ValidationError({"details": checker.errors})
                attrs["details"] = {k: v for k, v in checker.validated_data.items() if v not in (None, "")}

        if attrs.get("follow_up_on") and not entry_type.allows_follow_up:
            raise serializers.ValidationError({"follow_up_on": _("This type of entry has no follow-up date.")})
        return attrs

    def to_representation(self, instance):
        return entry_data(instance, self.context["request"].user)


def entry_data(entry, user) -> dict:
    """A stored entry in the common timeline shape."""
    return {
        "id": f"entry:{entry.pk}",
        "entry_id": entry.pk,
        "kind": entry.kind,
        "source": "manual",
        "summary": entry.summary,
        "details": entry.details,
        "occurred_at": entry.occurred_at,
        "follow_up_on": entry.follow_up_on,
        "created_by_name": entry.created_by.full_name if entry.created_by else None,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        "editable": can_modify(user, entry),
        **registry.target_ref(entry.contact, entry.company),
    }
