"""Signal receivers shared by several apps.

Receivers must be module-level functions. Django keeps only weak references to them, so a
function defined inside AppConfig.ready() can be garbage-collected as soon as ready() returns
(newer Python versions free that frame at once), and the signal then silently does nothing.
"""
from django.db import models


def remove_attachment_files(sender, instance, **kwargs):
    """post_delete for models that store files (attachments, resource photos): delete the stored files too.
    Also runs when the parent (task, comment, message, announcement) is deleted, through the cascade."""
    for field in instance._meta.concrete_fields:
        if isinstance(field, models.FileField):
            f = getattr(instance, field.attname)
            if f:
                f.storage.delete(f.name)
