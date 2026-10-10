from django.apps import AppConfig


class ContactsConfig(AppConfig):
    name = "apps.contacts"
    label = "contacts"

    def ready(self):
        from apps.core import search
        from apps.dashboard import registry as dashboard

        from .widgets import contacts_by_status

        dashboard.register("contacts_by_status", contacts_by_status)

        from .visibility import visible_companies, visible_contacts

        search.register(
            "contacts",
            queryset=lambda user: visible_contacts(user).select_related("company"),
            fields=["first_name", "last_name", "email", "phone"],
            phone_fields=["phone_digits", "whatsapp_digits"],
            serialize=lambda c, viewer: {
                "id": c.pk,
                "title": c.full_name,
                "subtitle": c.phone or c.email,
                "url": f"/contacts/{c.pk}",
                "status": c.status,
                "company": c.company.name if c.company else None,
            },
            permission=("contacts", "view"),
        )
        search.register(
            "companies",
            queryset=lambda user: visible_companies(user),
            fields=["name", "city", "email", "phone"],
            phone_fields=["phone_digits"],
            serialize=lambda c, viewer: {
                "id": c.pk,
                "title": c.name,
                "subtitle": " · ".join(filter(None, [c.get_industry_display(), c.city])),
                "url": f"/companies/{c.pk}",
            },
            permission=("contacts", "view"),
        )
