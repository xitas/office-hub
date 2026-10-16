from decimal import Decimal

from django.urls import reverse
from rest_framework import serializers

from . import rules
from .models import Expense


def receipt_data(r) -> dict:
    return {
        "id": r.pk,
        "original_name": r.original_name,
        "size": r.size,
        "content_type": r.content_type,
        "kind": r.kind,
        # Relative API paths: the frontend fetches them with the user's token (they are not public links).
        "download_url": reverse("expense-receipt-download", args=[r.pk]).removeprefix("/api/v1"),
        "thumbnail_url": reverse("expense-receipt-thumbnail", args=[r.pk]).removeprefix("/api/v1") if r.thumbnail else None,
    }


class ExpenseSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.full_name", read_only=True)
    department_name = serializers.CharField(source="user.department.name", read_only=True, default=None)
    decided_by_name = serializers.CharField(source="decided_by.full_name", read_only=True, default=None)
    paid_by_name = serializers.CharField(source="paid_by.full_name", read_only=True, default=None)
    receipts = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()
    can_decide = serializers.SerializerMethodField()
    can_pay = serializers.SerializerMethodField()

    class Meta:
        model = Expense
        fields = [
            "id", "user", "user_name", "department_name", "title", "category", "amount", "currency", "spent_on",
            "description", "status", "decided_by_name", "decided_at", "decision_note", "paid_by_name", "paid_at",
            "payment_note", "receipts", "can_edit", "can_cancel", "can_decide", "can_pay", "created_at",
        ]
        read_only_fields = fields

    def _user(self):
        return self.context["request"].user

    def get_receipts(self, obj) -> list[dict]:
        return [receipt_data(r) for r in obj.receipts.all()]

    def get_can_edit(self, obj) -> bool:
        return rules.can_edit(self._user(), obj)

    def get_can_cancel(self, obj) -> bool:
        return rules.can_cancel(self._user(), obj)

    def get_can_decide(self, obj) -> bool:
        return rules.can_decide(self._user(), obj)

    def get_can_pay(self, obj) -> bool:
        return rules.can_pay(self._user(), obj)


class ExpenseInputSerializer(serializers.Serializer):
    """A claim; receipts come as multipart ``files``, and ``remove_receipts`` lists receipt ids to drop (edits)."""

    title = serializers.CharField(max_length=120)
    category = serializers.ChoiceField(choices=Expense.Category.choices)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"), max_value=Decimal("10000000"))
    spent_on = serializers.DateField()
    description = serializers.CharField(required=False, allow_blank=True, max_length=2000, default="")
    remove_receipts = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)

    def validate_title(self, value):
        if not value.strip():
            raise serializers.ValidationError(serializers.CharField.default_error_messages["blank"])
        return value.strip()


class ExpenseDecisionSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    note = serializers.CharField(required=False, allow_blank=True, max_length=300, default="")


class PaySerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=200, default="")
