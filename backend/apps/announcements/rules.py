"""Who sees, posts and manages announcements.

- Everyone sees announcements for everyone and for their own department, plus their own.
- Admins post to everyone or to any departments, and see, edit and delete every announcement.
- Managers post to their own department only.
- The author or an admin edits and deletes an announcement and sees its read receipts.
"""
from django.db.models import Q

from apps.accounts.models import User
from apps.core.office_time import office_today
from apps.core.permissions import ADMIN, MANAGER

from .models import Announcement


def is_admin(user) -> bool:
    return user.role == ADMIN or user.is_superuser


def visible_announcements(user):
    if is_admin(user):
        return Announcement.objects.all()
    q = Q(audience=Announcement.Audience.EVERYONE) | Q(created_by=user)
    if user.department_id:
        # An id subquery instead of a join, so no announcement appears twice.
        targeted = Announcement.departments.through.objects.filter(department_id=user.department_id).values("announcement_id")
        q |= Q(audience=Announcement.Audience.DEPARTMENTS, pk__in=targeted)
    return Announcement.objects.filter(q)


def current(qs, today=None):
    """Not expired: no expiry date, or it hasn't passed yet (the expiry day itself still counts)."""
    today = today or office_today()
    return qs.filter(Q(expires_on__isnull=True) | Q(expires_on__gte=today))


def expired(qs, today=None):
    return qs.filter(expires_on__lt=today or office_today())


def can_post(user) -> bool:
    return is_admin(user) or (user.role == MANAGER and user.department_id is not None)


def can_manage(user, announcement) -> bool:
    """Edit, delete and see read receipts."""
    return is_admin(user) or (announcement.created_by_id is not None and announcement.created_by_id == user.pk)


def audience_users(announcement, department_ids=None):
    """Active people the announcement is for (its author left out)."""
    qs = User.objects.filter(is_active=True)
    if announcement.audience == Announcement.Audience.DEPARTMENTS:
        if department_ids is None:
            department_ids = [d.pk for d in announcement.departments.all()]
        qs = qs.filter(department_id__in=department_ids)
    if announcement.created_by_id:
        qs = qs.exclude(pk=announcement.created_by_id)
    return qs
