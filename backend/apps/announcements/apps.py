from django.apps import AppConfig


class AnnouncementsConfig(AppConfig):
    name = "apps.announcements"
    label = "announcements"

    def ready(self):
        from django.db.models.signals import post_delete

        from apps.dashboard import registry as dashboard

        from . import services
        from .models import AnnouncementAttachment

        def remove_files(sender, instance, **kwargs):
            # Also runs when an announcement is deleted (cascade), so no file is left behind.
            for f in (instance.file, instance.thumbnail):
                if f:
                    f.storage.delete(f.name)

        post_delete.connect(remove_files, sender=AnnouncementAttachment, dispatch_uid="announcements.attachment.files")
        dashboard.register("announcements", services.unread_widget)
