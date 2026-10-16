"""Who sees and changes weekly goals (see models.py).

- Everyone sees office-wide goals, their department's goals and goals they own.
- Managers add, edit and delete their department's goals; admins any goal, including office-wide ones.
- Progress is recorded by the goal's owner, the department's managers and admins.
"""
from django.db.models import Q

from apps.leave.rules import is_admin, is_manager

from .models import WeeklyGoal


def visible_goals(user):
    if is_admin(user):
        return WeeklyGoal.objects.all()
    q = Q(department__isnull=True) | Q(owner=user)
    if user.department_id:
        q |= Q(department_id=user.department_id)
    return WeeklyGoal.objects.filter(q)


def can_plan_for(user, department_id) -> bool:
    """May this person add or change goals of this department (None = the whole office)?"""
    if is_admin(user):
        return True
    return is_manager(user) and department_id is not None and department_id == user.department_id


def can_manage(user, goal) -> bool:
    return can_plan_for(user, goal.department_id)


def can_record(user, goal) -> bool:
    return goal.owner_id == user.pk or can_manage(user, goal)
