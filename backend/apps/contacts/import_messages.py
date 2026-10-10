"""Import row messages, stored as {"code", "params"} and translated when shown.

Results are kept after an import runs and may be read later by someone using the other language,
so rows never store finished sentences. `params` hold raw values (names, cell text), field keys
(shown as the reader's column label) or, for errors raised by the API serializers, the English
message text (looked up in the catalog at display time).
"""
from django.utils.translation import gettext as _
from django.utils.translation import gettext_noop as N_

from .csv_io import COLUMNS

MESSAGES = {
    "first_name_required": N_("First name is required."),
    "company_name_required": N_("Company name is required."),
    "bad_phone": N_("%(field)s “%(value)s” doesn’t look like a phone number."),
    "bad_email": N_("“%(value)s” is not a valid email address."),
    "too_long": N_("%(field)s is too long (the limit is %(max)s characters)."),
    "unknown_status": N_("Unknown lead status “%(value)s”."),
    "unknown_industry": N_("Unknown industry “%(value)s”."),
    "too_many_tags": N_("Too many tags (the limit is %(max)s)."),
    "person_ambiguous": N_("More than one person is called “%(name)s”. Use their email instead."),
    "person_unknown": N_("Unknown person “%(name)s”."),
    "company_hidden": N_("Company “%(name)s” belongs to someone else, so contacts can’t be linked to it."),
    "company_not_found": N_("Company “%(name)s” not found."),
    "company_created": N_("New company “%(name)s” will be created."),
    "duplicate": N_("Already in the CRM as %(name)s."),
    "duplicate_hidden": N_("Already in the CRM, assigned to someone else."),
    "updates": N_("Updates %(name)s."),
    "fills": N_("Fills in: %(fields)s."),
    "adds_tags": N_("Adds tags: %(tags)s."),
    "nothing_new": N_("Already in the CRM as %(name)s, with nothing new to add."),
    "field_error": N_("%(field)s: %(text)s"),
    "error": N_("%(text)s"),
    "unexpected": N_("Unexpected error while saving this row."),
}

_LABELS = {c.key: c.label for cols in COLUMNS.values() for c in cols}


def msg(code: str, **params) -> dict:
    return {"code": code, "params": params}


def label(key: str) -> str:
    return str(_LABELS[key]) if key in _LABELS else key


def render(message: dict) -> str:
    """One message in the active language."""
    params = dict(message.get("params") or {})
    if "field" in params:
        params["field"] = label(params["field"])
    if "fields" in params:
        params["fields"] = _(", ").join(label(k) for k in params["fields"])
    if "tags" in params and isinstance(params["tags"], list):
        params["tags"] = ", ".join(params["tags"])
    if "text" in params:
        params["text"] = _(params["text"])
    template = MESSAGES.get(message.get("code"), "%(text)s")
    try:
        return _(template) % params
    except (KeyError, TypeError, ValueError):
        return str(params.get("text", message.get("code", "")))


def render_all(messages) -> list[str]:
    return [render(m) for m in messages or []]


def issue_reason(issue: dict) -> str:
    # Imports run before messages were stored as codes kept the finished sentence.
    if "messages" in issue:
        return " ".join(render_all(issue["messages"]))
    return issue.get("reason", "")
