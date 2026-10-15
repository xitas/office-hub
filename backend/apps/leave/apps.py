from django.apps import AppConfig


class LeaveConfig(AppConfig):
    name = "apps.leave"
    label = "leave"

    def ready(self):
        from . import integration

        integration.register()  # "Pending approvals" on the dashboard
