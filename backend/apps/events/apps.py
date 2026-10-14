from django.apps import AppConfig


class EventsConfig(AppConfig):
    name = "apps.events"
    label = "events"
    verbose_name = "Calendar"

    def ready(self):
        from . import integration

        integration.register()  # "Today's meetings and bookings" on the dashboard
