from django.contrib import admin

from .models import Company


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ["name", "industry", "city", "assigned_to", "updated_at"]
    list_filter = ["industry", "city"]
    search_fields = ["name", "email", "phone"]
