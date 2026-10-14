from django.contrib import admin

from .models import Event


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["title", "kind", "start", "end", "all_day", "organizer"]
    list_filter = ["kind", "all_day"]
    search_fields = ["title", "location"]
    raw_id_fields = ["organizer", "booking"]
    filter_horizontal = ["attendees", "departments"]
