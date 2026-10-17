from datetime import timedelta

from django.db.models import Exists, OuterRef, Q

from apps.contacts.models import ContactStatusChange
from apps.contacts.visibility import visible_companies, visible_contacts
from apps.core.office_time import office_today
from apps.core.permissions import has_perm

from .models import TimelineEntry
from .registry import auto_entry, target_name, target_path
from .serializers import entry_data

LIMIT = 8
SHOWN_KINDS = ("note", "call", "meeting", "email", "whatsapp")


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


FOLLOW_UP_DAYS = 7
FOLLOW_UP_LIMIT = 10


def follow_ups_due(user, limit=FOLLOW_UP_LIMIT):
    """My open client follow-ups due within a week, overdue ones first.

    Mine: its task is assigned to me, or (when no task was made) I logged the entry. That already limits
    the list to my own work, so a follow-up handed to me shows even if its contact belongs to someone
    else; it then links to the task (which I can open) rather than the contact.
    """
    if not has_perm(user, "contacts", "view"):
        return None
    from apps.tasks.models import Task

    today = office_today()
    tasks = Task.objects.filter(follow_up_of=OuterRef("pk"))
    mine = Q(Exists(tasks.filter(assignees=user))) | (Q(created_by=user) & ~Q(Exists(tasks)))
    entries = (
        TimelineEntry.objects.filter(follow_up_on__isnull=False, follow_up_done_at__isnull=True, follow_up_on__lte=today + timedelta(days=FOLLOW_UP_DAYS))
        .filter(mine)
        .select_related("contact", "company", "vendor")
        .prefetch_related("follow_up_tasks")
        .order_by("follow_up_on", "pk")[:limit]
    )
    items = []
    for e in entries:
        task = next(iter(e.follow_up_tasks.all()), None)
        items.append({
            "id": e.pk,
            "kind": e.kind,
            "title": target_name(e),
            "summary": (e.summary or "").strip().split("\n")[0][:120],
            "due_date": e.follow_up_on,
            "is_overdue": e.follow_up_on < today,
            "url": f"/tasks/{task.pk}" if task else target_path(e),
            "task_id": task.pk if task else None,
        })
    return items
