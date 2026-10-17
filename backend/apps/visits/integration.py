"""Visits elsewhere in the app: "Pending approvals" on the dashboard, the timeline of the contact, company or
vendor visited, and the calendar."""
from django.db.models import F, Q
from django.utils.translation import gettext as _

from apps.core.office_time import office_tz
from apps.core.permissions import has_perm
from apps.dashboard import approvals

from . import rules
from .models import Visit

TIMELINE_STATUSES = (Visit.Status.PLANNED, Visit.Status.DONE, Visit.Status.CANCELLED)


# ================================================================ pending approvals


def _approval_rows(user):
    return approvals.columns(
        rules.decidable_visits(user), "visit",
        a_created=F("created_at"), a_name=F("assigned_to__full_name"), a_label=F("title"), a_start=F("start"), a_end=F("end"),
    )


def _approval_item(r) -> dict:
    return {
        "id": f"visit:{r['a_id']}",
        "title": r["a_name"],
        "subtitle": f"{r['a_label']} · {r['a_start'].astimezone(office_tz()):%d/%m/%Y}",
        "badge": _("Visit"),
        "time": r["a_start"].isoformat(),
        "end": r["a_end"].isoformat(),
        "url": "/visits?tab=approvals",
    }


# ================================================================ timeline


def _entry(v):
    from apps.timeline.registry import auto_entry

    entry = auto_entry(
        uid=f"visit:{v.pk}", kind="visit", occurred_at=v.closed_at if v.status != Visit.Status.PLANNED and v.closed_at else v.start,
        summary=v.title, user=v.assigned_to,
        details={"visit_id": v.pk, "status": v.status, "purpose": v.purpose, "start": v.start.isoformat(), "end": v.end.isoformat(),
                 "note": v.close_note},
        contact=v.contact, company=v.company,
    )
    entry["created_at"] = v.created_at
    if v.vendor_id:
        entry["vendor"] = {"id": v.vendor_id, "name": v.vendor.name}
    return entry


def timeline_entries(user, contact_ids, company_ids):
    """Visits to these contacts or companies (planned, done or cancelled) that the user may see."""
    if not has_perm(user, "visits", "view"):
        return []
    visits = rules.visible_visits(user).filter(Q(contact_id__in=contact_ids) | Q(company_id__in=company_ids), status__in=TIMELINE_STATUSES)
    return [_entry(v) for v in visits.select_related("contact", "company", "vendor", "assigned_to")]


def vendor_timeline_entries(user, vendor_id):
    if not has_perm(user, "visits", "view"):
        return []
    visits = rules.visible_visits(user).filter(vendor_id=vendor_id, status__in=TIMELINE_STATUSES)
    return [_entry(v) for v in visits.select_related("contact", "company", "vendor", "assigned_to")]


# ================================================================ calendar


def calendar_items(user, start, end) -> list[dict]:
    """My visits (responsible or companion) between two moments, for the calendar's "Visits" layer."""
    mine = Visit.objects.filter(assigned_to=user).values("pk") | Visit.objects.filter(companions=user).values("pk")
    visits = (
        Visit.objects.filter(pk__in=mine, start__lt=end, end__gt=start)
        .exclude(status__in=[Visit.Status.CANCELLED, Visit.Status.REJECTED])
        .select_related("contact", "company", "vendor", "assigned_to")
    )
    return [{
        "key": f"visit:{v.pk}", "type": "visit", "id": v.pk, "title": v.title, "subtitle": v.place,
        "start": v.start.isoformat(), "end": v.end.isoformat(), "all_day": False, "location": ", ".join(x for x in (v.address, v.city) if x),
        "status": v.status, "organizer": v.assigned_to.full_name, "url": f"/visits?visit={v.pk}",
    } for v in visits]


def register():
    from apps.timeline import registry as timeline

    approvals.register("visit", _approval_rows, _approval_item)
    timeline.register_provider("visit", timeline_entries)
    timeline.register_vendor_provider("visit", vendor_timeline_entries)

