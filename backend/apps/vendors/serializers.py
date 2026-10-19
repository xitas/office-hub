from django.utils.translation import gettext as _
from rest_framework import serializers

from apps.bookings.serializers import FormBooleanField
from apps.core.geo import PIN_KWARGS, check_pin

from . import rules
from .models import Vendor, VendorCategory


class VendorCategorySerializer(serializers.ModelSerializer):
    vendor_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = VendorCategory
        fields = ["id", "name", "name_ur", "position", "is_active", "vendor_count"]

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError(_("Give the category a name."))
        return value.strip()


class VendorSerializer(serializers.ModelSerializer):
    categories = serializers.PrimaryKeyRelatedField(many=True, queryset=VendorCategory.objects.all(), required=False)
    preferred = FormBooleanField(required=False, default=False)
    is_active = FormBooleanField(required=False, default=True)
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True, default=None)
    can_curate = serializers.SerializerMethodField()

    class Meta:
        model = Vendor
        fields = [
            "id", "name", "categories", "contact_person", "phone", "whatsapp", "email", "website", "address", "city",
            "areas", "latitude", "longitude", "payment_terms", "notes", "rating", "preferred", "is_active", "created_by_name", "created_at",
            "updated_at", "can_curate",
        ]
        read_only_fields = ["created_at", "updated_at"]
        extra_kwargs = {"rating": {"min_value": 1, "max_value": 5}, **PIN_KWARGS}

    def get_can_curate(self, obj) -> bool:
        return rules.can_curate(self.context["request"].user)

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError(_("Give the vendor a name."))
        return value.strip()

    def validate(self, attrs):
        user = self.context["request"].user
        if not rules.can_curate(user):
            # Staff add and correct vendors; preferred and inactive are for managers and admins.
            for field, default in (("preferred", False), ("is_active", True)):
                current = getattr(self.instance, field) if self.instance else default
                if field in attrs and attrs[field] != current:
                    raise serializers.ValidationError({field: _("Only managers and admins change this.")})
        check_pin(attrs, self.instance)
        if self.instance is None and not any(attrs.get(f) for f in ("phone", "whatsapp", "email", "address")):
            raise serializers.ValidationError({"phone": _("Give at least a phone number, email or address.")})
        return attrs


class VendorRefSerializer(serializers.ModelSerializer):
    """A vendor named on a supply item, purchase request or expense."""

    class Meta:
        model = Vendor
        fields = ["id", "name"]
