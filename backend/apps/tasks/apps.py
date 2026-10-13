from django.apps import AppConfig


class TasksConfig(AppConfig):
    name = "apps.tasks"
    label = "tasks"

    def ready(self):
        from django.db.models.signals import post_delete

        from apps.core.signals import remove_attachment_files

        from .models import TaskAttachment

        post_delete.connect(remove_attachment_files, sender=TaskAttachment, dispatch_uid="tasks.attachment.files")

        from . import integration

        integration.register()  # timeline entries, dashboard widgets, global search
