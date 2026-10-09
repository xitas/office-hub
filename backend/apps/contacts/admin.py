from django.contrib import admin

from .models import Company, Contact, Tag


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ["name", "industry", "city", "assigned_to", "updated_at"]
    list_filter = ["industry", "city"]
    search_fields = ["name", "email", "phone"]


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ["first_name", "last_name", "company", "status", "city", "assigned_to", "updated_at"]
    list_filter = ["status", "city", "tags"]
    search_fields = ["first_name", "last_name", "email", "phone"]
    autocomplete_fields = ["company"]


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    search_fields = ["name"]
