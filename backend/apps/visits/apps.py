from django.apps import AppConfig


class VisitsConfig(AppConfig):
    name = "apps.visits"
    label = "visits"

    def ready(self):
        from django.db.models.signals import post_delete

        from apps.core.signals import remove_attachment_files

        from . import integration
        from .models import VisitPhoto

        post_delete.connect(remove_attachment_files, sender=VisitPhoto, dispatch_uid="visits.photo.files")
        integration.register()  # pending approvals, timeline entries
