from django.db.models import Count

from apps.core.permissions import ADMIN, MANAGER, has_perm

from .models import Contact
from .visibility import visible_contacts


def contacts_by_status(user):
    """Lead counts per status for the contacts this user can see (own / department / everyone)."""
    if not has_perm(user, "contacts", "view"):
        return None
    counts = dict(visible_contacts(user).order_by().values_list("status").annotate(n=Count("id", distinct=True)))
    if user.role == ADMIN or user.is_superuser:
        scope = "all"
    elif user.role == MANAGER and user.department_id:
        scope = "department"
    else:
        scope = "mine"
    return {
        "scope": scope,
        "total": sum(counts.values()),
        "counts": [{"status": s, "count": counts.get(s, 0)} for s in Contact.Status.values],
    }
