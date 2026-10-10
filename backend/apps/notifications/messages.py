"""Translatable notification messages.

Notifications created with a ``message_key`` store only the key and its params.
Title and body are rendered on demand, in whichever language is active: the
reader's request language for the API, the recipient's saved language for the
live push and the email. Add one renderer per message key.
"""
from contextlib import nullcontext

from django.utils import translation
from django.utils.translation import gettext as _


def _account_updated(params: dict) -> tuple[str, str]:
    from apps.accounts.models import User

    parts = []
    if "role" in params:
        parts.append(_("role is now %(role)s") % {"role": User.Role(params["role"]).label})
    if "department" in params:
        parts.append(_("department is now %(department)s") % {"department": params["department"] or _("none")})
    body = _("%(actor)s changed your account: %(changes)s.") % {
        "actor": params.get("actor", ""),
        "changes": _("; ").join(parts),
    }
    return _("Your account was updated"), body


def _login_failures(params: dict) -> tuple[str, str]:
    body = _(
        "There were %(count)s failed attempts to sign in to your account, so sign-in is slowed down for a while. "
        "If this wasn't you, change your password."
    ) % {"count": params.get("count", 0)}
    return _("Failed sign-in attempts on your account"), body


RENDERERS = {
    "account_updated": _account_updated,
    "login_failures": _login_failures,
}


def render(message_key: str, params: dict, language: str | None = None) -> tuple[str, str]:
    """Returns (title, body) in `language` (or the currently active language)."""
    with translation.override(language) if language else nullcontext():
        return RENDERERS[message_key](params or {})
