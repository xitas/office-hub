"""Who sees and decides leave.

- Everyone requests leave for themselves and sees their own requests and balances.
- Managers see their department's requests and balances, and approve or reject them (not their own).
- Admins see everything, approve anyone's request, manage leave types and change allowances.
  An admin's own request is approved at once; a manager's own request goes to the admins.
- Colleagues see who in their department is on approved leave (dates and type, not the reason).
"""
from django.db.models import Q

from apps.accounts.models import User
from apps.core.permissions import ADMIN, MANAGER

from .models import LeaveRequest


def is_admin(user) -> bool:
    return user.role == ADMIN or user.is_superuser


def is_manager(user) -> bool:
    return user.role == MANAGER and user.department_id is not None


def team_users(user):
    """People whose requests and balances this person manages (not themselves for managers)."""
    if is_admin(user):
        return User.objects.all()
    if is_manager(user):
        return User.objects.filter(department_id=user.department_id).exclude(pk=user.pk)
    return User.objects.none()


def can_decide(user, request) -> bool:
    if request.status != LeaveRequest.Status.PENDING:
        return False
    if is_admin(user):
        return True
    return is_manager(user) and request.user_id != user.pk and request.user.department_id == user.department_id


def decidable_requests(user):
    pending = LeaveRequest.objects.filter(status=LeaveRequest.Status.PENDING)
    if is_admin(user):
        return pending
    if is_manager(user):
        return pending.filter(user__department_id=user.department_id).exclude(user=user)
    return pending.none()


def visible_requests(user):
    """Full requests (with reasons): own, plus the team's for managers and admins."""
    if is_admin(user):
        return LeaveRequest.objects.all()
    q = Q(user=user)
    if is_manager(user):
        q |= Q(user__department_id=user.department_id)
    return LeaveRequest.objects.filter(q)


def department_leave(user):
    """Approved leave the person may see on the team view and calendar (colleagues' dates, no reasons)."""
    approved = LeaveRequest.objects.filter(status=LeaveRequest.Status.APPROVED)
    if is_admin(user):
        return approved
    if user.department_id:
        return approved.filter(Q(user__department_id=user.department_id) | Q(user=user))
    return approved.filter(user=user)


def can_cancel(user, request, today) -> bool:
    """The requester cancels a pending request or approved leave that hasn't started; admins any unfinished one."""
    if request.status not in LeaveRequest.HOLDING:
        return False
    if is_admin(user):
        return request.end_date >= today
    return request.user_id == user.pk and (request.status == LeaveRequest.Status.PENDING or request.start_date > today)


def approvers_for(requester):
    managers = User.objects.filter(is_active=True, role=MANAGER, department_id=requester.department_id).exclude(pk=requester.pk)
    if requester.department_id and managers.exists():
        return list(managers)
    return list(User.objects.filter(is_active=True, role=ADMIN).exclude(pk=requester.pk))
