"""Timeline extension points.

Entry types (stored in TimelineEntry):
    register_type(EntryType("call", _("Call"), CallDetailsSerializer, allows_follow_up=True))

Automatic entries (computed from other data, never stored twice):
    register_provider("status", status_entries)
    # provider(user, contact_ids, company_ids) -> list[dict] in the shape built by auto_entry()

The Tasks, Calendar and Messages modules plug in through these two functions.
"""
from dataclasses import dataclass
from typing import Callable

from rest_framework import serializers


@dataclass(frozen=True)
class EntryType:
    key: str
    label: str
    details_serializer: type[serializers.Serializer] | None = None
    allows_follow_up: bool = False
    requires_summary: bool = True
    # False for entries written by the system (e.g. "Imported"): not addable or editable through the API.
    creatable: bool = True


_types: dict[str, EntryType] = {}
_providers: dict[str, Callable] = {}


def register_type(entry_type: EntryType):
    _types[entry_type.key] = entry_type


def get_type(key: str) -> EntryType | None:
    return _types.get(key)


def type_keys() -> list[str]:
    return list(_types)


def register_provider(kind: str, provider: Callable):
    """`kind` is the type key the provider's entries use (so the type filter can skip it)."""
    _providers[kind] = provider


def providers() -> dict[str, Callable]:
    return dict(_providers)


def target_ref(contact=None, company=None) -> dict:
    return {
        "contact": {"id": contact.pk, "name": contact.full_name} if contact else None,
        "company": {"id": company.pk, "name": company.name} if company else None,
    }


def auto_entry(*, uid: str, kind: str, occurred_at, summary: str, user=None, details=None, contact=None, company=None) -> dict:
    """Common shape for computed entries (stored entries are serialised to the same shape)."""
    return {
        "id": uid,
        "entry_id": None,
        "kind": kind,
        "source": "auto",
        "summary": summary,
        "details": details or {},
        "occurred_at": occurred_at,
        "follow_up_on": None,
        "created_by_name": user.full_name if user else None,
        "created_at": occurred_at,
        "updated_at": occurred_at,
        "editable": False,
        **target_ref(contact, company),
    }
