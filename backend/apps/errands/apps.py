from django.apps import AppConfig


class ErrandsConfig(AppConfig):
    name = "apps.errands"
    label = "errands"

    def ready(self):
        from django.db.models.signals import post_delete

        from apps.core.signals import remove_attachment_files

        from . import integration
        from .models import ErrandPhoto

        post_delete.connect(remove_attachment_files, sender=ErrandPhoto, dispatch_uid="errands.photo.files")
        integration.register()  # timelines of the contact, company or vendor
