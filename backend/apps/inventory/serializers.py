from django.utils.translation import gettext as _
from rest_framework import serializers

from apps.vendors.models import Vendor

from . import rules
from .models import PurchaseRequest, StockMovement, SupplyItem


class SupplyItemSerializer(serializers.ModelSerializer):
    is_low = serializers.BooleanField(read_only=True)
    open_requests = serializers.IntegerField(read_only=True, default=0)
    supplier = serializers.PrimaryKeyRelatedField(queryset=Vendor.objects.filter(is_active=True), required=False, allow_null=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True, default=None)

    class Meta:
        model = SupplyItem
        fields = [
            "id", "name", "name_ur", "category", "unit", "quantity", "reorder_level", "location", "notes", "supplier",
            "supplier_name", "is_active", "is_low", "open_requests", "updated_at",
        ]
        read_only_fields = ["updated_at"]
        extra_kwargs = {"quantity": {"max_value": 1_000_000}, "reorder_level": {"max_value": 1_000_000}}

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError(_("Give the item a name."))
        return value.strip()

    def validate_unit(self, value):
        return value.strip() or "piece"

    def update(self, instance, validated_data):
        validated_data.pop("quantity", None)  # the count changes through stock in/out, so it has a history
        return super().update(instance, validated_data)


class StockChangeSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=StockMovement.Kind.choices)
    amount = serializers.IntegerField(min_value=0, max_value=1_000_000)
    note = serializers.CharField(required=False, allow_blank=True, max_length=300, default="")


class StockMovementSerializer(serializers.ModelSerializer):
    by_name = serializers.CharField(source="by.full_name", read_only=True, default=None)

    class Meta:
        model = StockMovement
        fields = ["id", "kind", "change", "quantity_after", "note", "purchase_request", "by_name", "created_at"]
        read_only_fields = fields


class PurchaseRequestSerializer(serializers.ModelSerializer):
    requested_by_name = serializers.CharField(source="requested_by.full_name", read_only=True)
    department_name = serializers.CharField(source="requested_by.department.name", read_only=True, default=None)
    item_name_ur = serializers.CharField(source="item.name_ur", read_only=True, default="")
    vendor_name = serializers.CharField(source="vendor.name", read_only=True, default=None)
    decided_by_name = serializers.CharField(source="decided_by.full_name", read_only=True, default=None)
    received_by_name = serializers.CharField(source="received_by.full_name", read_only=True, default=None)
    can_decide = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()
    can_receive = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseRequest
        fields = [
            "id", "item", "item_name", "item_name_ur", "quantity", "unit", "reason", "estimated_cost", "vendor", "vendor_name",
            "requested_by",
            "requested_by_name", "department_name", "status", "decided_by_name", "decided_at", "decision_note",
            "received_by_name", "received_at", "received_quantity", "can_decide", "can_cancel", "can_receive", "created_at",
        ]
        read_only_fields = fields

    def _user(self):
        return self.context["request"].user

    def get_can_decide(self, obj) -> bool:
        return rules.can_decide(self._user(), obj)

    def get_can_cancel(self, obj) -> bool:
        return rules.can_cancel(self._user(), obj)

    def get_can_receive(self, obj) -> bool:
        return rules.can_receive(self._user(), obj)


class PurchaseInputSerializer(serializers.Serializer):
    item = serializers.PrimaryKeyRelatedField(queryset=SupplyItem.objects.all(), required=False, allow_null=True, default=None)
    item_name = serializers.CharField(required=False, allow_blank=True, max_length=100, default="")
    quantity = serializers.IntegerField(min_value=1, max_value=100_000)
    unit = serializers.CharField(required=False, allow_blank=True, max_length=30, default="")
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")
    estimated_cost = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False, allow_null=True, default=None)
    vendor = serializers.PrimaryKeyRelatedField(queryset=Vendor.objects.filter(is_active=True), required=False, allow_null=True, default=None)


class PurchaseDecisionSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    note = serializers.CharField(required=False, allow_blank=True, max_length=300, default="")


class ReceiveSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1, max_value=100_000, required=False, allow_null=True, default=None)
    add_to_stock = serializers.BooleanField(required=False, default=True)
    vendor = serializers.PrimaryKeyRelatedField(queryset=Vendor.objects.filter(is_active=True), required=False, allow_null=True, default=None)
    note = serializers.CharField(required=False, allow_blank=True, max_length=300, default="")
