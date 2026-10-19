"""Who sees, asks for, gives, takes and does errands (see models.py).

- Everyone sees the errands they asked for or run, and their department's open ones (to take). Managers see their
  department's; admins see all.
- Anyone asks for an errand (it belongs to their department). The runner is someone active from that department:
  yourself, a colleague (as for tasks), or anyone for admins.
- Whoever asked, the department's managers and admins change, give out or cancel an errand that isn't finished.
- The runner (and the department's managers and admins) marks it on the way, done or not done.
"""
from django.db.models import Q

from apps.leave.rules import is_admin, is_manager

from .models import Errand


def visible_errands(user):
    if is_admin(user):
        return Errand.objects.all()
    q = Q(requested_by=user) | Q(assigned_to=user)
    if user.department_id:
        q |= Q(department_id=user.department_id, status=Errand.Status.OPEN)
        if is_manager(user):
            q |= Q(department_id=user.department_id)
    return Errand.objects.filter(q)


def manages(user, errand) -> bool:
    if is_admin(user):
        return True
    return is_manager(user) and errand.department_id is not None and errand.department_id == user.department_id


def can_run(user, person, department_id) -> bool:
    """May `user` give an errand of this department to `person`?"""
    if not person.is_active:
        return False
    if is_admin(user):
        return True
    return person.pk == user.pk or (department_id is not None and person.department_id == department_id == user.department_id)


def can_change(user, errand) -> bool:
    if errand.status not in Errand.ACTIVE:
        return False
    return errand.requested_by_id == user.pk or manages(user, errand)


def can_take(user, errand) -> bool:
    if errand.status != Errand.Status.OPEN:
        return False
    return is_admin(user) or (errand.department_id is not None and errand.department_id == user.department_id)


def can_progress(user, errand) -> bool:
    """On the way, done, not done."""
    if errand.status not in (Errand.Status.ASSIGNED, Errand.Status.ON_THE_WAY):
        return False
    return errand.assigned_to_id == user.pk or manages(user, errand)
