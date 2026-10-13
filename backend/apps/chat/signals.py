"""Default channels follow users and departments. Connected in ChatConfig.ready().

Module-level on purpose: Django holds receivers weakly, so a function defined inside ready()
could be garbage-collected and the signal would silently stop working (see apps.core.signals).
"""
from django.utils import timezone

from . import services
from .models import Conversation


def user_saved(sender, instance, created, update_fields=None, **kwargs):
    # Default channels follow the user's department and active state (not every save, e.g. last_login).
    if created or update_fields is None or {"department", "is_active"} & set(update_fields):
        services.sync_default_memberships(instance)


def department_saved(sender, instance, **kwargs):
    services.department_channel(instance)  # created, or renamed to match


def department_deleted(sender, instance, **kwargs):
    Conversation.objects.filter(is_default=True, department=instance).update(archived_at=timezone.now(), is_default=False)
