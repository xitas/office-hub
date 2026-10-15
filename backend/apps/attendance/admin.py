from django.contrib import admin

from .models import Attendance


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ["user", "date", "check_in", "check_out", "mode", "corrected_by"]
    list_filter = ["mode", "date"]
    raw_id_fields = ["user", "corrected_by"]
