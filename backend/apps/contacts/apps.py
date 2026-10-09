from django.apps import AppConfig


class ContactsConfig(AppConfig):
    name = "apps.contacts"
    label = "contacts"

    def ready(self):
        from apps.core import search

        from .visibility import visible_companies, visible_contacts

        search.register(
            "contacts",
            queryset=lambda user: visible_contacts(user).select_related("company"),
            fields=["first_name", "last_name", "email", "phone", "phone_digits", "whatsapp_digits"],
            serialize=lambda c, viewer: {
                "id": c.pk,
                "title": c.full_name,
                "subtitle": " · ".join(filter(None, [c.company.name if c.company else "", c.phone or c.email])),
                "url": f"/contacts/{c.pk}",
            },
            permission=("contacts", "view"),
        )
        search.register(
            "companies",
            queryset=lambda user: visible_companies(user),
            fields=["name", "city", "email", "phone"],
            serialize=lambda c, viewer: {
                "id": c.pk,
                "title": c.name,
                "subtitle": " · ".join(filter(None, [c.get_industry_display(), c.city])),
                "url": f"/companies/{c.pk}",
            },
            permission=("contacts", "view"),
        )
