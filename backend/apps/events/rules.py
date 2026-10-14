"""Who sees, adds and changes calendar items.

- Holidays: everyone sees them; admins add, change and remove them.
- Office events: for everyone or chosen departments. Managers add them for their own department,
  admins for anyone.
- Meetings: anyone organizes one. The organizer and attendees see it (admins see all).
- The organizer or an admin changes or removes an item.
"""
from django.db.models import Q

from apps.accounts.models import User
from apps.core.permissions import ADMIN, MANAGER

from .models import Event


def is_admin(user) -> bool:
    return user.role == ADMIN or user.is_superuser


def visible_events(user):
    if is_admin(user):
        return Event.objects.all()
    invited = Event.attendees.through.objects.filter(user_id=user.pk).values("event_id")
    q = Q(kind=Event.Kind.HOLIDAY) | Q(organizer=user) | Q(pk__in=invited)
    q |= Q(kind=Event.Kind.EVENT, audience=Event.Audience.EVERYONE)
    if user.department_id:
        targeted = Event.departments.through.objects.filter(department_id=user.department_id).values("event_id")
        q |= Q(kind=Event.Kind.EVENT, audience=Event.Audience.DEPARTMENTS, pk__in=targeted)
    return Event.objects.filter(q)


def can_add(user, kind: str, audience: str, department_ids: set[int]) -> bool:
    if kind == Event.Kind.MEETING:
        return True
    if kind == Event.Kind.HOLIDAY:
        return is_admin(user)
    if is_admin(user):
        return True
    return (
        user.role == MANAGER and user.department_id is not None
        and audience == Event.Audience.DEPARTMENTS and department_ids == {user.department_id}
    )


def can_manage(user, event) -> bool:
    if is_admin(user):
        return True
    return event.kind != Event.Kind.HOLIDAY and event.organizer_id is not None and event.organizer_id == user.pk


def audience_users(event):
    """Who an office event or holiday is for (active people)."""
    qs = User.objects.filter(is_active=True)
    if event.kind == Event.Kind.EVENT and event.audience == Event.Audience.DEPARTMENTS:
        qs = qs.filter(department__in=event.departments.all())
    return qs
