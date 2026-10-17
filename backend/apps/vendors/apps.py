from django.apps import AppConfig


class VendorsConfig(AppConfig):
    name = "apps.vendors"
    label = "vendors"

    def ready(self):
        from apps.core import search

        from .models import Vendor

        search.register(
            "vendors",
            queryset=lambda user: Vendor.objects.filter(is_active=True),
            fields=["name", "contact_person", "city", "areas"],
            phone_fields=["phone_digits", "whatsapp_digits"],
            serialize=lambda v, viewer: {
                "id": v.pk,
                "title": v.name,
                "subtitle": " · ".join(filter(None, [v.contact_person, v.city])),
                "url": f"/vendors/{v.pk}",
            },
            permission=("vendors", "view"),
        )
