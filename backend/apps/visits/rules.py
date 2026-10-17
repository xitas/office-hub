"""Who sees, plans, changes and decides field visits (see models.py).

- Everyone sees the visits they go on (responsible or companion) and those they planned; managers see their
  department's; admins see all.
- Staff plan visits for themselves; managers for anyone in their department; admins for anyone.
- The person going, whoever planned it, the department's managers and admins change, close or cancel an
  open visit. Managers decide their department's requests (not their own); admins decide any.
"""
from django.db.models import Q

from apps.accounts.models import User
from apps.core.models import OrganizationSettings
from apps.leave.rules import approvers_for, is_admin, is_manager  # noqa: F401 (same approvers as leave)

from .models import Visit


def visible_visits(user):
    if is_admin(user):
        return Visit.objects.all()
    q = Q(assigned_to=user) | Q(companions=user) | Q(created_by=user)
    if is_manager(user):
        q |= Q(assigned_to__department_id=user.department_id)
    # (companions can repeat a row through the join; the subquery keeps each visit once)
    return Visit.objects.filter(pk__in=Visit.objects.filter(q).values("pk"))


def can_plan_for(user, person) -> bool:
    if person.pk == user.pk or is_admin(user):
        return True
    return is_manager(user) and person.department_id == user.department_id


def planners_people(user):
    """Whom this person may plan visits for."""
    if is_admin(user):
        return User.objects.filter(is_active=True)
    if is_manager(user):
        return User.objects.filter(is_active=True, department_id=user.department_id)
    return User.objects.filter(pk=user.pk)


def manages(user, visit) -> bool:
    if is_admin(user):
        return True
    return is_manager(user) and visit.assigned_to.department_id == user.department_id


def can_change(user, visit) -> bool:
    if visit.status not in Visit.OPEN:
        return False
    return visit.assigned_to_id == user.pk or visit.created_by_id == user.pk or manages(user, visit)


def can_close(user, visit) -> bool:
    """Mark done: the people who went, and the department's managers and admins (planned visits only)."""
    if visit.status != Visit.Status.PLANNED:
        return False
    return visit.assigned_to_id == user.pk or manages(user, visit) or any(c.pk == user.pk for c in visit.companions.all())


def can_decide(user, visit) -> bool:
    if visit.status != Visit.Status.PENDING or visit.assigned_to_id == user.pk:
        return False
    return manages(user, visit)


def decidable_visits(user):
    pending = Visit.objects.filter(status=Visit.Status.PENDING)
    if is_admin(user):
        return pending.exclude(assigned_to=user)
    if is_manager(user):
        return pending.filter(assigned_to__department_id=user.department_id).exclude(assigned_to=user)
    return pending.none()


def needs_approval(planner, person) -> bool:
    """A staff member planning their own visit asks first (when the Organization setting is on)."""
    if not OrganizationSettings.cached().visits_need_approval:
        return False
    return person.pk == planner.pk and not (is_admin(planner) or is_manager(planner)) and bool(approvers_for(person))
