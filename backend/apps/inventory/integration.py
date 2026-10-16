"""Purchase requests waiting for my decision join the dashboard's "Pending approvals"."""
from django.db.models import F, Value
from django.db.models.functions import Coalesce
from django.utils import translation
from django.utils.translation import gettext as _

from apps.dashboard import approvals

from . import rules


def _rows(user):
    return approvals.columns(
        rules.decidable_requests(user), "purchase",
        a_created=F("created_at"), a_name=F("requested_by__full_name"), a_label=F("item_name"),
        a_label_ur=Coalesce(F("item__name_ur"), Value("")), a_number=F("quantity"), a_extra=F("unit"),
    )


def _item(r) -> dict:
    urdu = (translation.get_language() or "").startswith("ur")
    name = r["a_label_ur"] if urdu and r["a_label_ur"] else r["a_label"]
    quantity = f"{r['a_number'].normalize():f}"
    return {
        "id": f"purchase:{r['a_id']}",
        "title": r["a_name"],
        "subtitle": f"{name} · {quantity} {r['a_extra']}".strip(),
        "badge": _("Supplies"),
        "time": None,
        "url": "/supplies?tab=requests",
    }


def register():
    approvals.register("purchase", _rows, _item)
