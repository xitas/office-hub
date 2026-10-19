"""Errands elsewhere in the app: the timeline of the contact, company or vendor (e.g. the courier company)."""
from django.db.models import Q

from apps.core.permissions import has_perm

from . import rules
from .models import Errand

SHOWN = (Errand.Status.ASSIGNED, Errand.Status.ON_THE_WAY, Errand.Status.OPEN, Errand.Status.DONE, Errand.Status.FAILED)


def _entry(e):
    from apps.timeline.registry import auto_entry

    entry = auto_entry(
        uid=f"errand:{e.pk}", kind="errand", occurred_at=e.finished_at or e.due_at or e.created_at, summary=e.title,
        user=e.assigned_to or e.requested_by,
        details={"errand_id": e.pk, "status": e.status, "errand_kind": e.kind, "reference": e.reference, "note": e.outcome_note},
        contact=e.contact, company=e.company,
    )
    entry["created_at"] = e.created_at
    if e.vendor_id:
        entry["vendor"] = {"id": e.vendor_id, "name": e.vendor.name}
    return entry


def timeline_entries(user, contact_ids, company_ids):
    if not has_perm(user, "errands", "view"):
        return []
    errands = rules.visible_errands(user).filter(Q(contact_id__in=contact_ids) | Q(company_id__in=company_ids), status__in=SHOWN)
    return [_entry(e) for e in errands.select_related("contact", "company", "vendor", "assigned_to", "requested_by")]


def vendor_timeline_entries(user, vendor_id):
    if not has_perm(user, "errands", "view"):
        return []
    errands = rules.visible_errands(user).filter(vendor_id=vendor_id, status__in=SHOWN)
    return [_entry(e) for e in errands.select_related("contact", "company", "vendor", "assigned_to", "requested_by")]


def register():
    from apps.timeline import registry as timeline

    timeline.register_provider("errand", timeline_entries)
    timeline.register_vendor_provider("errand", vendor_timeline_entries)
