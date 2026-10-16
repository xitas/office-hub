"""Expense claims, receipts, decisions and payment (used by the API, the seed command and tests)."""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models import OrganizationSettings
from apps.core.office_time import office_today
from apps.notifications.models import NotificationType
from apps.notifications.services import notify
from apps.tasks.files import FileRejected, check_upload, make_thumbnail

from . import rules
from .models import Expense, ExpenseReceipt

MAX_RECEIPTS = 5
MAX_AGE_DAYS = 365
LINK = "/expenses"
APPROVALS_LINK = "/expenses?tab=approvals"


class ExpenseError(ValueError):
    """{field: message}"""

    def __init__(self, errors: dict):
        self.errors = errors
        super().__init__(next(iter(errors.values())))


def money(amount, currency: str) -> str:
    """"PKR 4,500" / "PKR 1,250.50": Latin digits, so it reads the same in Urdu and English."""
    amount = Decimal(amount)
    text = f"{amount:,.0f}" if amount == amount.to_integral() else f"{amount:,.2f}"
    return f"{currency} {text}"


def _check(spent_on, amount):
    today = office_today()
    if spent_on > today:
        raise ExpenseError({"spent_on": _("The day it was spent can't be in the future.")})
    if spent_on < today - timedelta(days=MAX_AGE_DAYS):
        raise ExpenseError({"spent_on": _("Claims can go back one year at most.")})
    if amount <= 0:
        raise ExpenseError({"amount": _("Give an amount above zero.")})


def save_receipts(expense, uploader, files, keep=0):
    """Check every file first (all or nothing), then store them privately with random names."""
    if keep + len(files) > MAX_RECEIPTS:
        raise ExpenseError({"files": _("A claim can have up to %(n)s receipts.") % {"n": MAX_RECEIPTS}})
    checked = []
    for upload in files:
        try:
            checked.append((upload, check_upload(upload)))
        except FileRejected as exc:
            raise ExpenseError({"files": str(exc)})
    for upload, info in checked:
        receipt = ExpenseReceipt(
            expense=expense, original_name=upload.name[:255], size=upload.size,
            content_type=info.content_type, kind=info.kind, uploaded_by=uploader,
        )
        thumb = make_thumbnail(upload) if info.kind == "image" else None
        receipt.file.save(f"upload.{info.extension}", upload, save=False)
        if thumb:
            receipt.thumbnail.save("thumb.webp", thumb, save=False)
        receipt.save()


def claim(user, *, title, category, amount, spent_on, description="", files=()) -> Expense:
    _check(spent_on, amount)
    approvers = rules.approvers_for(user)
    auto = not approvers  # an admin with no other admin to ask
    with transaction.atomic():
        expense = Expense.objects.create(
            user=user, title=title.strip()[:120], category=category, amount=amount,
            currency=OrganizationSettings.cached().currency, spent_on=spent_on, description=description.strip(),
            status=Expense.Status.APPROVED if auto else Expense.Status.PENDING,
            decided_by=user if auto else None, decided_at=timezone.now() if auto else None,
        )
        save_receipts(expense, user, list(files))
        if not auto:
            pk = expense.pk
            transaction.on_commit(lambda: _announce_claim(pk))
    return expense


def update(user, expense, changes: dict, files=(), remove=()) -> dict:
    """Change a waiting claim; returns {field: [old, new]} for the audit log."""
    if not rules.can_edit(user, expense):
        raise PermissionError
    spent_on, amount = changes.get("spent_on", expense.spent_on), changes.get("amount", expense.amount)
    _check(spent_on, amount)
    out = {}
    with transaction.atomic():
        for field, value in changes.items():
            old = getattr(expense, field)
            if value != old:
                out[field] = [str(old), str(value)]
                setattr(expense, field, value)
        expense.save()
        if remove:
            gone = list(expense.receipts.filter(pk__in=remove))
            for receipt in gone:
                receipt.delete()  # the post_delete signal removes the files
            if gone:
                out["receipts_removed"] = [", ".join(r.original_name for r in gone), None]
        if files:
            save_receipts(expense, user, list(files), keep=expense.receipts.count())
            out["receipts_added"] = [None, ", ".join(f.name for f in files)]
    return out


def decide(user, expense, *, approve: bool, note="") -> Expense:
    if not rules.can_decide(user, expense):
        raise PermissionError
    expense.status = Expense.Status.APPROVED if approve else Expense.Status.REJECTED
    expense.decided_by, expense.decided_at, expense.decision_note = user, timezone.now(), note.strip()[:300]
    expense.save(update_fields=["status", "decided_by", "decided_at", "decision_note", "updated_at"])
    pk = expense.pk
    transaction.on_commit(lambda: _announce(pk, "expense_approved" if approve else "expense_rejected", user.pk))
    return expense


def cancel(user, expense) -> Expense:
    if not rules.can_cancel(user, expense):
        raise PermissionError
    was = expense.status
    expense.status = Expense.Status.CANCELLED
    expense.save(update_fields=["status", "updated_at"])
    pk = expense.pk
    if expense.user_id == user.pk:
        def tell():
            e = Expense.objects.select_related("user", "decided_by").get(pk=pk)
            people = [e.decided_by] if was == Expense.Status.APPROVED and e.decided_by else rules.approvers_for(e.user)
            notify(people, NotificationType.APPROVAL_RESULT, link=APPROVALS_LINK, actor=e.user, message="expense_cancelled",
                   params=_params(e, e.user))
        transaction.on_commit(tell)
    else:
        transaction.on_commit(lambda: _announce(pk, "expense_cancelled", user.pk))
    return expense


def pay(user, expense, note="") -> Expense:
    if not rules.can_pay(user, expense):
        raise PermissionError
    expense.status = Expense.Status.PAID
    expense.paid_by, expense.paid_at, expense.payment_note = user, timezone.now(), note.strip()[:200]
    expense.save(update_fields=["status", "paid_by", "paid_at", "payment_note", "updated_at"])
    pk = expense.pk
    transaction.on_commit(lambda: _announce(pk, "expense_paid", user.pk))
    return expense


# ================================================================ notifications


def _params(expense, actor=None) -> dict:
    return {
        "name": expense.user.full_name,
        "title": expense.title,
        "amount": str(expense.amount),
        "currency": expense.currency,
        "date": expense.spent_on.isoformat(),
        "actor": actor.full_name if actor else "",
        "note": expense.decision_note,
        "payment_note": expense.payment_note,
    }


def _announce_claim(pk):
    expense = Expense.objects.select_related("user").get(pk=pk)
    notify(rules.approvers_for(expense.user), NotificationType.APPROVAL_REQUEST, link=APPROVALS_LINK, actor=expense.user,
           message="expense_claim", params=_params(expense, expense.user))


def _announce(pk, message, actor_pk):
    from apps.accounts.models import User

    expense = Expense.objects.select_related("user").get(pk=pk)
    actor = User.objects.get(pk=actor_pk)
    notify(expense.user, NotificationType.APPROVAL_RESULT, link=LINK, actor=actor, message=message, params=_params(expense, actor))
