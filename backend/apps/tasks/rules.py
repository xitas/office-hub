"""Who sees, assigns and deletes tasks.

- See: staff the tasks they created or are assigned to; managers also every task created by or
  assigned to someone in their department; admins everything.
- Assign: everyone may assign themselves and colleagues in their own department; admins anyone.
- Delete: admins and managers (tasks they can see), staff only tasks they created.
"""
from django.db.models import Q

from apps.core.permissions import ADMIN, MANAGER, has_perm

from .models import Task


def is_admin(user) -> bool:
    return user.role == ADMIN or user.is_superuser


def visible_tasks(user, queryset=None):
    qs = Task.objects.all() if queryset is None else queryset
    if is_admin(user):
        return qs
    visible = Q(created_by=user) | Q(assignees=user)
    if user.role == MANAGER and user.department_id:
        visible |= Q(created_by__department_id=user.department_id) | Q(assignees__department_id=user.department_id)
    return qs.filter(visible).distinct()


def assignable_users(user, queryset):
    """Users `user` may put on a task."""
    if is_admin(user):
        return queryset
    if user.department_id and has_perm(user, "tasks", "assign_others"):
        return queryset.filter(Q(pk=user.pk) | Q(department_id=user.department_id))
    return queryset.filter(pk=user.pk)


def can_delete(user, task) -> bool:
    if not has_perm(user, "tasks", "delete"):
        return False
    if is_admin(user) or user.role == MANAGER:
        return True
    return task.created_by_id == user.pk
