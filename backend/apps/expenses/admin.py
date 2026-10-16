from django.contrib import admin

from .models import Expense, ExpenseReceipt


class ReceiptInline(admin.TabularInline):
    model = ExpenseReceipt
    extra = 0
    fields = ["original_name", "size", "kind", "created_at"]
    readonly_fields = fields


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ["title", "user", "category", "amount", "currency", "spent_on", "status"]
    list_filter = ["status", "category"]
    raw_id_fields = ["user", "decided_by", "paid_by"]
    inlines = [ReceiptInline]
