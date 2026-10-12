from django.apps import AppConfig


class ChatConfig(AppConfig):
    name = "apps.chat"
    label = "chat"

    def ready(self):
        from django.db.models.signals import post_save, pre_delete

        from apps.accounts.models import Department, User

        from . import services

        def user_saved(sender, instance, created, update_fields=None, **kwargs):
            # Default channels follow the user's department and active state (not every save, e.g. last_login).
            if created or update_fields is None or {"department", "is_active"} & set(update_fields):
                services.sync_default_memberships(instance)

        def department_saved(sender, instance, **kwargs):
            services.department_channel(instance)  # created, or renamed to match

        def department_deleted(sender, instance, **kwargs):
            from django.utils import timezone

            from .models import Conversation

            Conversation.objects.filter(is_default=True, department=instance).update(archived_at=timezone.now(), is_default=False)

        from .models import MessageAttachment

        def remove_files(sender, instance, **kwargs):
            # Also runs when a message or conversation is deleted (cascade), so no file is left behind.
            for f in (instance.file, instance.thumbnail):
                if f:
                    f.storage.delete(f.name)

        from django.db.models.signals import post_delete

        post_delete.connect(remove_files, sender=MessageAttachment, dispatch_uid="chat.attachment.files")
        from . import integration

        integration.register()  # dashboard widgets, messages in global search
        post_save.connect(user_saved, sender=User, dispatch_uid="chat.user_saved")
        post_save.connect(department_saved, sender=Department, dispatch_uid="chat.department_saved")
        pre_delete.connect(department_deleted, sender=Department, dispatch_uid="chat.department_deleted")
