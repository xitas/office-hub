"""Expense claims waiting for my decision join the dashboard's "Pending approvals"."""
from django.db.models import F
from django.utils.translation import gettext as _

from apps.dashboard import approvals

from . import rules
from .services import money


def _rows(user):
    return approvals.columns(
        rules.decidable_expenses(user), "expense",
        a_created=F("created_at"), a_name=F("user__full_name"), a_label=F("title"), a_first=F("spent_on"),
        a_number=F("amount"), a_extra=F("currency"),
    )


def _item(r) -> dict:
    return {
        "id": f"expense:{r['a_id']}",
        "title": r["a_name"],
        "subtitle": f"{r['a_label']} · {money(r['a_number'], r['a_extra'])} · {r['a_first']:%d/%m/%Y}",
        "badge": _("Expense"),
        "time": None,
        "url": "/expenses?tab=approvals",
    }


def register():
    approvals.register("expense", _rows, _item)
