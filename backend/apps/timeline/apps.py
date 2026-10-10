from django.apps import AppConfig


class TimelineConfig(AppConfig):
    name = "apps.timeline"
    label = "timeline"

    def ready(self):
        from apps.dashboard import registry as dashboard

        from . import builtin  # noqa: F401  registers the built-in entry types and automatic entries
        from .widgets import client_activity

        dashboard.register("client_activity", client_activity)
