"""Who sees, decides and pays expense claims (see models.py)."""
from django.db.models import Q

from apps.accounts.models import User
from apps.core.permissions import ADMIN, MANAGER
from apps.leave.rules import is_admin, is_manager

from .models import Expense


def visible_expenses(user):
    if is_admin(user):
        return Expense.objects.all()
    q = Q(user=user)
    if is_manager(user):
        q |= Q(user__department_id=user.department_id)
    return Expense.objects.filter(q)


def team_users(user):
    if is_admin(user):
        return User.objects.all()
    if is_manager(user):
        return User.objects.filter(department_id=user.department_id)
    return User.objects.filter(pk=user.pk)


def decidable_expenses(user):
    pending = Expense.objects.filter(status=Expense.Status.PENDING)
    if is_admin(user):
        return pending.exclude(user=user)
    if is_manager(user):
        return pending.filter(user__department_id=user.department_id).exclude(user=user)
    return pending.none()


def can_decide(user, expense) -> bool:
    if expense.status != Expense.Status.PENDING or expense.user_id == user.pk:
        return False
    if is_admin(user):
        return True
    return is_manager(user) and expense.user.department_id == user.department_id


def can_edit(user, expense) -> bool:
    """The claimant changes a claim (and its receipts) while it waits."""
    return expense.status == Expense.Status.PENDING and expense.user_id == user.pk


def can_cancel(user, expense) -> bool:
    if expense.status == Expense.Status.PENDING and expense.user_id == user.pk:
        return True
    return is_admin(user) and expense.status in (Expense.Status.PENDING, Expense.Status.APPROVED)


def can_pay(user, expense) -> bool:
    return is_admin(user) and expense.status == Expense.Status.APPROVED


def approvers_for(claimant):
    """Managers of the claimant's department (not themselves); admins when there are none. Never the claimant."""
    managers = User.objects.filter(is_active=True, role=MANAGER, department_id=claimant.department_id).exclude(pk=claimant.pk)
    if claimant.role != ADMIN and claimant.department_id and managers.exists():
        return list(managers)
    return list(User.objects.filter(is_active=True, role=ADMIN).exclude(pk=claimant.pk))
