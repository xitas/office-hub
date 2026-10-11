from django.apps import AppConfig


class TasksConfig(AppConfig):
    name = "apps.tasks"
    label = "tasks"

    def ready(self):
        from django.db.models.signals import post_delete

        from .models import TaskAttachment

        def remove_files(sender, instance, **kwargs):
            # Also runs when a task or comment is deleted (cascade), so no file is left behind.
            for f in (instance.file, instance.thumbnail):
                if f:
                    f.storage.delete(f.name)

        post_delete.connect(remove_files, sender=TaskAttachment, dispatch_uid="tasks.attachment.files")

        from . import integration

        integration.register()  # timeline entries, dashboard widgets, global search
