from django.db.models import Q

from apps.contacts.models import ContactStatusChange
from apps.contacts.visibility import visible_companies, visible_contacts
from apps.core.permissions import has_perm

from .models import TimelineEntry
from .registry import auto_entry
from .serializers import entry_data

LIMIT = 8
SHOWN_KINDS = ("note", "call", "meeting")


def client_activity(user, limit=LIMIT):
    """Latest logged notes, calls, meetings and status changes on records the user can see."""
    if not has_perm(user, "contacts", "view"):
        return None
    contacts, companies = visible_contacts(user), visible_companies(user)
    entries = (
        TimelineEntry.objects.filter(kind__in=SHOWN_KINDS)
        .filter(Q(contact__in=contacts) | Q(company__in=companies))
        .select_related("contact", "company", "created_by__department")[:limit]
    )
    changes = (
        ContactStatusChange.objects.filter(contact__in=contacts)
        .exclude(from_status="")
        .select_related("contact", "changed_by")[:limit]
    )
    items = [entry_data(e, user) for e in entries] + [
        auto_entry(
            uid=f"status:{c.pk}", kind="status", occurred_at=c.changed_at, summary=c.reason, user=c.changed_by,
            details={"from": c.from_status, "to": c.to_status}, contact=c.contact,
        )
        for c in changes
    ]
    items.sort(key=lambda e: e["occurred_at"], reverse=True)
    return items[:limit]
