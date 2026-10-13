"""Who sees, shares and changes templates.

- Everyone uses templates shared with everyone, their department's, and their own.
- Anyone creates personal templates ("only me").
- Managers also share with their department and change their department's shared templates.
- Admins share with everyone, and see and change every template.
"""
from django.db.models import Q

from apps.core.permissions import ADMIN, MANAGER

from .models import MessageTemplate


def is_admin(user) -> bool:
    return user.role == ADMIN or user.is_superuser


def visible_templates(user):
    if is_admin(user):
        return MessageTemplate.objects.all()
    q = Q(sharing=MessageTemplate.Sharing.EVERYONE) | Q(created_by=user)
    if user.department_id:
        q |= Q(sharing=MessageTemplate.Sharing.DEPARTMENT, department_id=user.department_id)
    return MessageTemplate.objects.filter(q)


def can_share(user, sharing: str) -> bool:
    if sharing == MessageTemplate.Sharing.PERSONAL:
        return True
    if sharing == MessageTemplate.Sharing.DEPARTMENT:
        return is_admin(user) or (user.role == MANAGER and user.department_id is not None)
    return is_admin(user)


def can_edit(user, template) -> bool:
    if is_admin(user) or template.created_by_id == user.pk:
        return True
    return (
        user.role == MANAGER
        and template.sharing == MessageTemplate.Sharing.DEPARTMENT
        and template.department_id is not None
        and template.department_id == user.department_id
    )
