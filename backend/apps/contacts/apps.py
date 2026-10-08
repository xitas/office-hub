from django.apps import AppConfig


class ContactsConfig(AppConfig):
    name = "apps.contacts"
    label = "contacts"

    def ready(self):
        from django.db.models import Q

        from apps.core import search
        from apps.core.permissions import ADMIN, MANAGER

        from .models import Company

        def companies_for(user):
            # Same visibility as the API: staff -> assigned to them, managers -> department, admins -> all.
            qs = Company.objects.select_related("assigned_to")
            if user.role == ADMIN or user.is_superuser:
                return qs
            visible = Q(assigned_to=user)
            if user.role == MANAGER and user.department_id:
                visible |= Q(assigned_to__department_id=user.department_id)
            return qs.filter(visible)

        search.register(
            "companies",
            queryset=companies_for,
            fields=["name", "city", "email", "phone"],
            serialize=lambda c, viewer: {
                "id": c.pk,
                "title": c.name,
                "subtitle": " · ".join(filter(None, [c.get_industry_display(), c.city])),
                "url": f"/companies/{c.pk}",
            },
            permission=("contacts", "view"),
        )
