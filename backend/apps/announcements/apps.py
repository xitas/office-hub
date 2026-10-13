from django.apps import AppConfig


class AnnouncementsConfig(AppConfig):
    name = "apps.announcements"
    label = "announcements"

    def ready(self):
        from django.db.models.signals import post_delete

        from apps.core.signals import remove_attachment_files
        from apps.dashboard import registry as dashboard

        from . import services
        from .models import AnnouncementAttachment

        post_delete.connect(remove_attachment_files, sender=AnnouncementAttachment, dispatch_uid="announcements.attachment.files")
        dashboard.register("announcements", services.unread_widget)
