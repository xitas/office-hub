from django.apps import AppConfig


class VisitsConfig(AppConfig):
    name = "apps.visits"
    label = "visits"

    def ready(self):
        from . import integration

        integration.register()  # pending approvals, timeline entries
