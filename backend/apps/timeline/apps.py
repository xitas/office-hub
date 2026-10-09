from django.apps import AppConfig


class TimelineConfig(AppConfig):
    name = "apps.timeline"
    label = "timeline"

    def ready(self):
        from . import builtin  # noqa: F401  registers the built-in entry types and automatic entries
