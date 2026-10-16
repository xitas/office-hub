from django.apps import AppConfig


class InventoryConfig(AppConfig):
    name = "apps.inventory"
    label = "inventory"

    def ready(self):
        from . import integration

        integration.register()  # purchase requests in "Pending approvals"
