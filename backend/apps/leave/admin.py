from django.contrib import admin

from .models import LeaveBalance, LeaveRequest, LeaveType


@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "days_per_year", "paid", "allow_half_days", "is_active"]


@admin.register(LeaveBalance)
class LeaveBalanceAdmin(admin.ModelAdmin):
    list_display = ["user", "leave_type", "year", "allowance"]
    list_filter = ["year", "leave_type"]


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ["user", "leave_type", "start_date", "end_date", "days", "status"]
    list_filter = ["status", "leave_type"]
    raw_id_fields = ["user", "decided_by", "cancelled_by"]
