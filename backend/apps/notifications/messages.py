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


def _task_comment(params: dict) -> tuple[str, str]:
    return (
        _("New comment on “%(task)s”") % {"task": params.get("task", "")},
        _("%(actor)s commented on the task.") % {"actor": params.get("actor", "")},
    )


def _task_mention(params: dict) -> tuple[str, str]:
    return (
        _("%(actor)s mentioned you") % {"actor": params.get("actor", "")},
        _("In a comment on “%(task)s”.") % {"task": params.get("task", "")},
    )


def _task_assigned(params: dict) -> tuple[str, str]:
    return (
        _("New task: “%(task)s”") % {"task": params.get("task", "")},
        _("%(actor)s assigned you a task.") % {"actor": params.get("actor") or _("Someone")},
    )


def _task_due_soon(params: dict) -> tuple[str, str]:
    from django.utils.dateparse import parse_datetime

    from apps.core.office_time import clock, office_tz

    due = parse_datetime(params.get("due", "") or "")
    when = ""
    if due:
        local = due.astimezone(office_tz())
        when = f"{local:%d/%m/%Y} {clock(due)}" if params.get("has_time") else local.strftime("%d/%m/%Y")
    return (
        _("Due soon: “%(task)s”") % {"task": params.get("task", "")},
        _("This task is due %(when)s.") % {"when": when},
    )


def _task_overdue(params: dict) -> tuple[str, str]:
    return (
        _("Overdue: “%(task)s”") % {"task": params.get("task", "")},
        _("This task is past its due date and still open."),
    )


def _chat_direct(params: dict) -> tuple[str, str]:
    return _("Message from %(actor)s") % {"actor": params.get("actor", "")}, params.get("preview", "")


def _chat_channel(params: dict) -> tuple[str, str]:
    return (
        _("New message in #%(channel)s") % {"channel": _("General") if params.get("general") else params.get("channel", "")},
        "%s: %s" % (params.get("actor", ""), params.get("preview", "")),
    )


def _chat_mention(params: dict) -> tuple[str, str]:
    actor = params.get("actor", "")
    if "channel" not in params:
        title = _("%(actor)s mentioned you") % {"actor": actor}
    else:
        channel = _("General") if params.get("general") else params.get("channel", "")
        title = (
            _("%(actor)s mentioned you in #%(channel)s") if params.get("kind", "direct") == "direct"
            else _("%(actor)s notified everyone in #%(channel)s")
        ) % {"actor": actor, "channel": channel}
    return title, params.get("preview", "")


def _announcement(params: dict) -> tuple[str, str]:
    return (
        _("New announcement: %(title)s") % {"title": params.get("title", "")},
        "%s: %s" % (params.get("actor", ""), params.get("preview", "")) if params.get("actor") else params.get("preview", ""),
    )


def _booking_when(params: dict) -> str:
    """ "14/10/2026 10:00–11:00" in the office time zone (date and times as the office reads them)."""
    from django.utils.dateparse import parse_datetime

    from apps.core.office_time import clock, office_tz

    start, end = parse_datetime(params.get("start", "") or ""), parse_datetime(params.get("end", "") or "")
    if not start or not end:
        return ""
    return f"{start.astimezone(office_tz()):%d/%m/%Y} {clock(start)}–{clock(end)}"


def _booking_detail(params: dict) -> str:
    text = "%s · %s · %s" % (params.get("title", ""), params.get("resource", ""), _booking_when(params))
    if params.get("more"):
        text += " " + _("(and %(n)s more dates)") % {"n": params["more"]}
    return text


def _booking_request(params: dict) -> tuple[str, str]:
    return _("%(actor)s asks to book %(resource)s") % params, _booking_detail(params)


def _booking_approved(params: dict) -> tuple[str, str]:
    return _("Booking approved: %(resource)s") % params, _booking_detail(params)


def _booking_rejected(params: dict) -> tuple[str, str]:
    body = _booking_detail(params)
    if params.get("reason"):
        body += "\n" + _("Reason: %(reason)s") % {"reason": params["reason"]}
    return _("Booking rejected: %(resource)s") % params, body


def _booking_invited(params: dict) -> tuple[str, str]:
    return _("%(actor)s booked %(resource)s with you") % params, _booking_detail(params)


def _booking_changed(params: dict) -> tuple[str, str]:
    return _("Booking changed: %(title)s") % params, _booking_detail(params)


def _booking_cancelled(params: dict) -> tuple[str, str]:
    return _("Booking cancelled: %(title)s") % params, _booking_detail(params)


def _booking_reminder(params: dict) -> tuple[str, str]:
    return _("Starts in 15 minutes: %(title)s") % params, _booking_detail(params)


def _event_when(params: dict) -> str:
    """ "14/10/2026 2:30 pm–3:30 pm", or the day(s) for all-day items, in the office time zone."""
    from datetime import timedelta

    from django.utils.dateparse import parse_datetime

    from apps.core.office_time import clock, office_tz

    start, end = parse_datetime(params.get("start", "") or ""), parse_datetime(params.get("end", "") or "")
    if not start or not end:
        return ""
    s, e = start.astimezone(office_tz()), end.astimezone(office_tz())
    if params.get("all_day"):
        last = (e - timedelta(days=1)).date()
        return f"{s:%d/%m/%Y}" if last == s.date() else f"{s:%d/%m/%Y}–{last:%d/%m/%Y}"
    return f"{s:%d/%m/%Y} {clock(start)}–{clock(end)}"


def _event_detail(params: dict) -> str:
    parts = [_event_when(params)]
    if params.get("location"):
        parts.append(params["location"])
    return " · ".join(p for p in parts if p)


def _meeting_invite(params: dict) -> tuple[str, str]:
    return _("%(actor)s invited you: %(title)s") % params, _event_detail(params)


def _meeting_changed(params: dict) -> tuple[str, str]:
    return _("Meeting changed: %(title)s") % params, _event_detail(params)


def _meeting_cancelled(params: dict) -> tuple[str, str]:
    return _("Meeting cancelled: %(title)s") % params, _event_detail(params)


def _meeting_reminder(params: dict) -> tuple[str, str]:
    return _("Meeting in 15 minutes: %(title)s") % params, _event_detail(params)


def _event_added(params: dict) -> tuple[str, str]:
    return _("New office event: %(title)s") % params, _event_detail(params)


def _holiday_added(params: dict) -> tuple[str, str]:
    return _("Office holiday: %(title)s") % params, _event_detail(params)


def _leave_detail(params: dict) -> str:
    from datetime import date

    from django.utils import translation

    lang = translation.get_language() or ""
    kind = params.get("type_ur") if params.get("type_ur") and lang.startswith("ur") else params.get("type", "")
    try:
        first, last = date.fromisoformat(params.get("start", "")), date.fromisoformat(params.get("end", ""))
    except ValueError:
        return kind
    when = f"{first:%d/%m/%Y}" if first == last else f"{first:%d/%m/%Y}–{last:%d/%m/%Y}"
    days = _("%(n)s days") % {"n": params.get("days", "")}
    if params.get("half_day"):
        days = _("half a day (morning)") if params["half_day"] == "morning" else _("half a day (afternoon)")
    return f"{kind} · {when} · {days}"


def _leave_request(params: dict) -> tuple[str, str]:
    return _("%(name)s asks for leave") % params, _leave_detail(params)


def _leave_approved(params: dict) -> tuple[str, str]:
    return _("Leave approved"), _leave_detail(params)


def _leave_rejected(params: dict) -> tuple[str, str]:
    body = _leave_detail(params)
    if params.get("note"):
        body += "\n" + _("Note: %(note)s") % {"note": params["note"]}
    return _("Leave not approved"), body


def _leave_cancelled(params: dict) -> tuple[str, str]:
    return _("Leave cancelled: %(name)s") % params, _leave_detail(params)


RENDERERS = {
    "leave_request": _leave_request,
    "leave_approved": _leave_approved,
    "leave_rejected": _leave_rejected,
    "leave_cancelled": _leave_cancelled,
    "meeting_invite": _meeting_invite,
    "meeting_changed": _meeting_changed,
    "meeting_cancelled": _meeting_cancelled,
    "meeting_reminder": _meeting_reminder,
    "event_added": _event_added,
    "holiday_added": _holiday_added,
    "booking_request": _booking_request,
    "booking_approved": _booking_approved,
    "booking_rejected": _booking_rejected,
    "booking_invited": _booking_invited,
    "booking_changed": _booking_changed,
    "booking_cancelled": _booking_cancelled,
    "booking_reminder": _booking_reminder,
    "announcement": _announcement,
    "chat_mention": _chat_mention,
    "chat_direct": _chat_direct,
    "chat_channel": _chat_channel,
    "task_assigned": _task_assigned,
    "task_due_soon": _task_due_soon,
    "task_overdue": _task_overdue,
    "account_updated": _account_updated,
    "login_failures": _login_failures,
    "task_comment": _task_comment,
    "task_mention": _task_mention,
}


def render(message_key: str, params: dict, language: str | None = None) -> tuple[str, str]:
    """Returns (title, body) in `language` (or the currently active language)."""
    with translation.override(language) if language else nullcontext():
        return RENDERERS[message_key](params or {})
