from django.apps import AppConfig


class DashboardConfig(AppConfig):
    name = "apps.dashboard"
    label = "dashboard"

    def ready(self):
        from . import registry, widgets

        registry.register("activity", widgets.activity)
        registry.register("unread_notifications", widgets.unread_notifications)
