"""Stock changes, low-stock alerts and purchase requests (used by the API, the seed command and tests)."""
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.notifications.models import NotificationType
from apps.notifications.services import notify

from . import rules
from .models import PurchaseRequest, StockMovement, SupplyItem

REQUESTS_LINK = "/supplies?tab=requests"


class SupplyError(ValueError):
    """{field: message}"""

    def __init__(self, errors: dict):
        self.errors = errors
        super().__init__(next(iter(errors.values())))


# ================================================================ stock


def change_stock(user, item, kind, amount: int, note="", purchase_request=None) -> StockMovement:
    """Received / taken out add or remove `amount`; a corrected count sets the quantity to `amount`.

    The item row is locked, so two people recording at once can't lose a change. Alerts the supply managers
    when the quantity drops to the reorder level or below (once each time it crosses).
    """
    with transaction.atomic():
        item = SupplyItem.objects.select_for_update().get(pk=item.pk)
        before = item.quantity
        if kind == StockMovement.Kind.ADJUSTED:
            if amount < 0:
                raise SupplyError({"amount": _("The count can't be below zero.")})
            after = amount
        else:
            if amount <= 0:
                raise SupplyError({"amount": _("Give a quantity of at least 1.")})
            after = before + amount if kind == StockMovement.Kind.RECEIVED else before - amount
            if after < 0:
                raise SupplyError({"amount": _("Only %(n)s in stock.") % {"n": before}})
        item.quantity = after
        item.save(update_fields=["quantity", "updated_at"])
        movement = StockMovement.objects.create(
            item=item, kind=kind, change=after - before, quantity_after=after, note=note.strip()[:300],
            purchase_request=purchase_request, by=user,
        )
        if before > item.reorder_level >= after:
            pk, actor_pk = item.pk, user.pk if user else None
            transaction.on_commit(lambda: _announce_low(pk, actor_pk))
    return movement


def _announce_low(pk, actor_pk):
    from apps.accounts.models import User

    item = SupplyItem.objects.get(pk=pk)
    if not item.is_low:  # restocked meanwhile
        return
    actor = User.objects.filter(pk=actor_pk).first() if actor_pk else None
    notify(rules.supply_managers(), NotificationType.LOW_STOCK, link=f"/supplies?item={item.pk}", actor=actor,
           message="low_stock", params={"item": item.name, "item_ur": item.name_ur, "quantity": item.quantity,
                                        "unit": item.unit, "level": item.reorder_level})


# ================================================================ purchase requests


def request_purchase(user, *, item=None, item_name="", quantity: int, unit="", reason="", estimated_cost=None) -> PurchaseRequest:
    if item is not None:
        if not item.is_active:
            raise SupplyError({"item": _("This item isn't stocked any more.")})
        item_name, unit = item.name, unit or item.unit
    item_name = item_name.strip()
    if not item_name:
        raise SupplyError({"item_name": _("Say what to buy.")})
    auto = rules.is_admin(user)
    with transaction.atomic():
        req = PurchaseRequest.objects.create(
            item=item, item_name=item_name[:100], quantity=quantity, unit=unit.strip()[:30], reason=reason.strip()[:500],
            estimated_cost=estimated_cost, requested_by=user,
            status=PurchaseRequest.Status.APPROVED if auto else PurchaseRequest.Status.PENDING,
            decided_by=user if auto else None, decided_at=timezone.now() if auto else None,
        )
        if not auto:
            pk = req.pk
            transaction.on_commit(lambda: _announce_request(pk))
    return req


def decide(user, req, *, approve: bool, note="") -> PurchaseRequest:
    if not rules.can_decide(user, req):
        raise PermissionError
    req.status = PurchaseRequest.Status.APPROVED if approve else PurchaseRequest.Status.REJECTED
    req.decided_by, req.decided_at, req.decision_note = user, timezone.now(), note.strip()[:300]
    req.save(update_fields=["status", "decided_by", "decided_at", "decision_note", "updated_at"])
    pk = req.pk
    transaction.on_commit(lambda: _announce(pk, "purchase_approved" if approve else "purchase_rejected", user.pk))
    return req


def cancel(user, req) -> PurchaseRequest:
    if not rules.can_cancel(user, req):
        raise PermissionError
    was = req.status
    req.status = PurchaseRequest.Status.CANCELLED
    req.save(update_fields=["status", "updated_at"])
    pk = req.pk
    if req.requested_by_id == user.pk:
        # The requester withdrew it: whoever would decide (or approved it) is told.
        def tell():
            r = PurchaseRequest.objects.select_related("requested_by", "decided_by").get(pk=pk)
            people = [r.decided_by] if was == PurchaseRequest.Status.APPROVED and r.decided_by else rules.approvers_for(r.requested_by)
            notify(people, NotificationType.APPROVAL_RESULT, link=REQUESTS_LINK, actor=r.requested_by,
                   message="purchase_cancelled", params=_params(r, r.requested_by))
        transaction.on_commit(tell)
    else:
        transaction.on_commit(lambda: _announce(pk, "purchase_cancelled", user.pk))
    return req


def receive(user, req, *, quantity=None, add_to_stock=True, note="") -> PurchaseRequest:
    """Mark an approved request received. Adds it to stock (a new item is added to the list) unless told not to."""
    if not rules.can_receive(user, req):
        raise PermissionError
    quantity = quantity or req.quantity
    with transaction.atomic():
        req = PurchaseRequest.objects.select_for_update().get(pk=req.pk)
        if req.status != PurchaseRequest.Status.APPROVED:
            raise PermissionError
        if add_to_stock:
            item = req.item
            if item is None:
                item = SupplyItem.objects.create(name=req.item_name, unit=req.unit or "piece", category=SupplyItem.Category.OTHER, created_by=user)
                req.item = item
            change_stock(user, item, StockMovement.Kind.RECEIVED, quantity, note or _("Purchase request #%(n)s") % {"n": req.pk}, purchase_request=req)
        req.status = PurchaseRequest.Status.RECEIVED
        req.received_by, req.received_at, req.received_quantity = user, timezone.now(), quantity
        req.save(update_fields=["item", "status", "received_by", "received_at", "received_quantity", "updated_at"])
        pk = req.pk
        transaction.on_commit(lambda: _announce(pk, "purchase_received", user.pk))
    return req


# ================================================================ notifications


def _params(req, actor=None) -> dict:
    return {
        "name": req.requested_by.full_name,
        "item": req.item_name,
        "item_ur": req.item.name_ur if req.item_id and req.item else "",
        "quantity": req.received_quantity or req.quantity,
        "unit": req.unit,
        "actor": actor.full_name if actor else "",
        "note": req.decision_note,
        "reason": req.reason,
    }


def _announce_request(pk):
    req = PurchaseRequest.objects.select_related("requested_by", "item").get(pk=pk)
    notify(rules.approvers_for(req.requested_by), NotificationType.APPROVAL_REQUEST, link=REQUESTS_LINK,
           actor=req.requested_by, message="purchase_request", params=_params(req, req.requested_by))


def _announce(pk, message, actor_pk):
    from apps.accounts.models import User

    req = PurchaseRequest.objects.select_related("requested_by", "item").get(pk=pk)
    actor = User.objects.get(pk=actor_pk)
    notify(req.requested_by, NotificationType.APPROVAL_RESULT, link=REQUESTS_LINK, actor=actor, message=message,
           params=_params(req, actor))
