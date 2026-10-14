"""Signal receivers must stay connected.

Django keeps receivers as weak references. A receiver defined inside AppConfig.ready() can be
garbage-collected once ready() returns; on Python 3.13.16 that happens at once (3.13.3 happened to
keep it alive), and the signal silently stops: no department channels, no files removed.
"""
import gc
import weakref

import pytest
from django.db.models import signals

from apps.accounts.models import Department, User
from apps.announcements.models import AnnouncementAttachment
from apps.bookings.models import Resource
from apps.chat.models import Conversation, MessageAttachment
from apps.tasks.models import Task, TaskAttachment

EXPECTED = [
    (signals.post_save, User),
    (signals.post_save, Department),
    (signals.pre_delete, Department),
    (signals.post_save, Task),
    (signals.post_delete, TaskAttachment),
    (signals.post_delete, MessageAttachment),
    (signals.post_delete, AnnouncementAttachment),
    (signals.post_delete, Resource),
]


@pytest.mark.parametrize("signal,sender", EXPECTED, ids=lambda x: getattr(x, "__name__", ""))
def test_receivers_are_connected_and_survive_garbage_collection(signal, sender):
    gc.collect()
    assert signal.has_listeners(sender), f"no live receiver for {sender.__name__}"


def test_project_receivers_are_module_level_functions():
    """Catches the pattern on any Python version: a nested function is only weakly held."""
    gc.collect()
    for signal in (signals.post_save, signals.pre_delete, signals.post_delete):
        for _key, ref, _is_async in signal.receivers:
            func = ref() if isinstance(ref, weakref.ReferenceType) else ref
            if func is None or not getattr(func, "__module__", "").startswith("apps."):
                continue
            assert "<locals>" not in func.__qualname__, f"{func.__module__}.{func.__qualname__} is defined inside a function"


@pytest.mark.django_db
def test_a_new_department_gets_its_channel():
    department = Department.objects.create(name="Logistics")
    assert Conversation.objects.filter(is_default=True, department=department).exists()
