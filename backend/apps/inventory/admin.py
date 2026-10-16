from django.contrib import admin

from .models import PurchaseRequest, StockMovement, SupplyItem


@admin.register(SupplyItem)
class SupplyItemAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "quantity", "unit", "reorder_level", "is_active"]
    list_filter = ["category", "is_active"]
    search_fields = ["name", "name_ur"]


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ["item", "kind", "change", "quantity_after", "by", "created_at"]
    list_filter = ["kind"]
    raw_id_fields = ["item", "by", "purchase_request"]


@admin.register(PurchaseRequest)
class PurchaseRequestAdmin(admin.ModelAdmin):
    list_display = ["item_name", "quantity", "requested_by", "status", "created_at"]
    list_filter = ["status"]
    raw_id_fields = ["item", "requested_by", "decided_by", "received_by"]
