"""Who sees and decides supplies.

- Everyone sees the active items and their stock, and asks for things to be bought (their own requests).
- Managers and admins look after supplies: add and edit items, record stock in and out, see every request,
  and mark approved requests received. Admins delete unused items.
- Managers approve their department's requests (not their own); admins approve anyone's.
"""
from apps.accounts.models import User
from apps.core.permissions import ADMIN, MANAGER, has_perm
from apps.leave.rules import approvers_for, is_admin, is_manager  # noqa: F401 (same approvers as leave)

from .models import PurchaseRequest


def can_manage(user) -> bool:
    return has_perm(user, "inventory", "edit")


def visible_requests(user):
    if can_manage(user):
        return PurchaseRequest.objects.all()
    return PurchaseRequest.objects.filter(requested_by=user)


def decidable_requests(user):
    pending = PurchaseRequest.objects.filter(status=PurchaseRequest.Status.PENDING)
    if is_admin(user):
        return pending
    if is_manager(user):
        return pending.filter(requested_by__department_id=user.department_id).exclude(requested_by=user)
    return pending.none()


def can_decide(user, req) -> bool:
    if req.status != PurchaseRequest.Status.PENDING:
        return False
    if is_admin(user):
        return True
    return is_manager(user) and req.requested_by_id != user.pk and req.requested_by.department_id == user.department_id


def can_cancel(user, req) -> bool:
    """The requester withdraws a waiting request; managers and admins drop one that's waiting or not bought yet."""
    if req.status == PurchaseRequest.Status.PENDING and req.requested_by_id == user.pk:
        return True
    return can_manage(user) and req.status in (PurchaseRequest.Status.PENDING, PurchaseRequest.Status.APPROVED)


def can_receive(user, req) -> bool:
    return req.status == PurchaseRequest.Status.APPROVED and can_manage(user)


def supply_managers():
    """Who is alerted about low stock."""
    return list(User.objects.filter(is_active=True, role__in=[ADMIN, MANAGER]))
