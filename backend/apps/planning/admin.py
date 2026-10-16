from django.contrib import admin

from .models import GoalUpdate, WeeklyGoal


@admin.register(WeeklyGoal)
class WeeklyGoalAdmin(admin.ModelAdmin):
    list_display = ["title", "week_start", "department", "owner", "current", "target", "unit"]
    list_filter = ["week_start", "department"]
    raw_id_fields = ["owner", "created_by", "carried_from"]


@admin.register(GoalUpdate)
class GoalUpdateAdmin(admin.ModelAdmin):
    list_display = ["goal", "before", "after", "by", "created_at"]
    raw_id_fields = ["goal", "by"]
