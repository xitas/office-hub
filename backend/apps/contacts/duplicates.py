"""Duplicate-contact warnings (never blocking).

Matches on any shared phone/WhatsApp number (normalised) or email (ignoring case),
across *all* contacts so a salesperson learns a client is already in the CRM even
when it's assigned to someone else — but details are only revealed for contacts
the user is allowed to see.
"""
from django.db.models import Q

from .models import Contact
from .phones import normalize_phone
from .visibility import visible_contacts

LIMIT = 5


def find_duplicates(user, *, phone="", whatsapp="", email="", exclude_id=None) -> list[dict]:
    numbers = {n for n in (normalize_phone(phone), normalize_phone(whatsapp)) if len(n) >= 7}
    email = (email or "").strip()
    match = Q()
    if numbers:
        match |= Q(phone_digits__in=numbers) | Q(whatsapp_digits__in=numbers)
    if email:
        match |= Q(email__iexact=email)
    if not match:
        return []

    candidates = Contact.objects.filter(match).select_related("company", "assigned_to")
    if exclude_id:
        candidates = candidates.exclude(pk=exclude_id)
    visible_ids = set(visible_contacts(user).filter(pk__in=[c.pk for c in candidates[:LIMIT]]).values_list("pk", flat=True))

    results = []
    for c in candidates[:LIMIT]:
        matched = []
        if numbers and ({c.phone_digits, c.whatsapp_digits} & numbers):
            matched.append("phone")
        if email and c.email.lower() == email.lower():
            matched.append("email")
        if c.pk in visible_ids:
            results.append({
                "id": c.pk,
                "name": c.full_name,
                "company_name": c.company.name if c.company else None,
                "assigned_to_name": c.assigned_to.full_name if c.assigned_to else None,
                "matched": matched,
                "visible": True,
            })
        else:
            # Exists, but belongs to someone this user can't see: say so without details.
            results.append({
                "id": None,
                "name": None,
                "company_name": None,
                "assigned_to_name": c.assigned_to.full_name if c.assigned_to else None,
                "matched": matched,
                "visible": False,
            })
    return results
