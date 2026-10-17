from django.contrib import admin

from .models import Vendor, VendorCategory


@admin.register(VendorCategory)
class VendorCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "name_ur", "position", "is_active"]


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ["name", "contact_person", "phone", "city", "preferred", "is_active"]
    list_filter = ["preferred", "is_active", "categories"]
    search_fields = ["name", "contact_person", "phone", "city", "areas"]
    raw_id_fields = ["created_by", "updated_by"]
