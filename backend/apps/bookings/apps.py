from django.apps import AppConfig


class BookingsConfig(AppConfig):
    name = "apps.bookings"
    label = "bookings"

    def ready(self):
        from django.db.models.signals import post_delete

        from apps.core.signals import remove_attachment_files

        from . import integration
        from .models import Resource

        post_delete.connect(remove_attachment_files, sender=Resource, dispatch_uid="bookings.resource.photo")
        integration.register()  # dashboard widgets
