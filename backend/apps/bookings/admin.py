from django.contrib import admin

from .models import Booking, Resource


@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = ["name", "type", "capacity", "location", "bookable_by", "needs_approval", "is_active"]
    list_filter = ["type", "needs_approval", "is_active"]
    search_fields = ["name", "location"]
    filter_horizontal = ["departments"]


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ["title", "resource", "start", "end", "booked_by", "status"]
    list_filter = ["status", "resource"]
    search_fields = ["title"]
    raw_id_fields = ["booked_by", "decided_by", "cancelled_by", "series"]
    filter_horizontal = ["attendees"]
