from django.apps import AppConfig


class ChatConfig(AppConfig):
    name = "apps.chat"
    label = "chat"

    def ready(self):
        from django.db.models.signals import post_delete, post_save, pre_delete

        from apps.accounts.models import Department, User
        from apps.core.signals import remove_attachment_files

        from . import integration, signals
        from .models import MessageAttachment

        post_delete.connect(remove_attachment_files, sender=MessageAttachment, dispatch_uid="chat.attachment.files")
        post_save.connect(signals.user_saved, sender=User, dispatch_uid="chat.user_saved")
        post_save.connect(signals.department_saved, sender=Department, dispatch_uid="chat.department_saved")
        pre_delete.connect(signals.department_deleted, sender=Department, dispatch_uid="chat.department_deleted")
        integration.register()  # dashboard widgets, messages in global search
