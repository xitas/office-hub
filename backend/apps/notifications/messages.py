"""Translatable notification messages.

Notifications created with a ``message_key`` store only the key and its params.
Title and body are rendered on demand, in whichever language is active: the
reader's request language for the API, the recipient's saved language for the
live push and the email. Add one renderer per message key.
"""
from contextlib import nullcontext

from django.utils import translation
from django.utils.translation import gettext as _
from django.utils.translation import ngettext


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


def _attendance_check_in(params: dict) -> tuple[str, str]:
    from datetime import datetime

    from apps.core.office_time import clock

    try:
        opens = clock(datetime.fromisoformat(params.get("opens", "")).time())
    except ValueError:
        opens = ""
    return _("Forgot to check in?"), _("You haven't checked in today. The office opened at %(time)s.") % {"time": opens}


def _attendance_check_out(params: dict) -> tuple[str, str]:
    from django.utils.dateparse import parse_datetime

    from apps.core.office_time import clock

    at = parse_datetime(params.get("check_in", "") or "")
    return _("Forgot to check out?"), _("You checked in at %(time)s and haven't checked out yet.") % {"time": clock(at) if at else ""}


def _attendance_corrected(params: dict) -> tuple[str, str]:
    from datetime import date

    from django.utils.dateparse import parse_datetime

    from apps.core.office_time import clock

    try:
        day = date.fromisoformat(params.get("date", "")).strftime("%d/%m/%Y")
    except ValueError:
        day = ""
    if params.get("cleared"):
        body = _("%(actor)s removed your attendance record for %(date)s.") % {"actor": params.get("actor", ""), "date": day}
    else:
        start, end = parse_datetime(params.get("check_in", "") or ""), parse_datetime(params.get("check_out", "") or "")
        times = f"{clock(start)}–{clock(end)}" if start and end else (clock(start) if start else "")
        body = _("%(actor)s set your attendance for %(date)s: %(times)s.") % {"actor": params.get("actor", ""), "date": day, "times": times}
    return _("Attendance corrected"), body


def _item_name(params: dict) -> str:
    from django.utils import translation

    urdu = (translation.get_language() or "").startswith("ur")
    return params.get("item_ur") if urdu and params.get("item_ur") else params.get("item", "")


def _purchase_detail(params: dict) -> str:
    return f"{_item_name(params)} · {params.get('quantity', '')} {params.get('unit', '')}".strip()


def _with_note(body: str, params: dict, key="note") -> str:
    if params.get(key):
        body += "\n" + _("Note: %(note)s") % {"note": params[key]}
    return body


def _low_stock(params: dict) -> tuple[str, str]:
    return _("Low stock: %(item)s") % {"item": _item_name(params)}, _(
        "%(quantity)s %(unit)s left (reorder level %(level)s)."
    ) % {"quantity": params.get("quantity", ""), "unit": params.get("unit", ""), "level": params.get("level", "")}


def _purchase_request(params: dict) -> tuple[str, str]:
    return _("%(name)s asks to buy supplies") % params, _with_note(_purchase_detail(params), {"note": params.get("reason", "")})


def _purchase_approved(params: dict) -> tuple[str, str]:
    return _("Purchase request approved"), _with_note(_purchase_detail(params), params)


def _purchase_rejected(params: dict) -> tuple[str, str]:
    return _("Purchase request not approved"), _with_note(_purchase_detail(params), params)


def _purchase_received(params: dict) -> tuple[str, str]:
    return _("Your supplies have arrived"), _purchase_detail(params)


def _purchase_cancelled(params: dict) -> tuple[str, str]:
    return _("Purchase request cancelled: %(name)s") % params, _purchase_detail(params)


def _expense_detail(params: dict) -> str:
    from datetime import date

    from apps.expenses.services import money

    try:
        day = date.fromisoformat(params.get("date", "")).strftime("%d/%m/%Y")
    except ValueError:
        day = ""
    try:
        amount = money(params.get("amount", "0"), params.get("currency", ""))
    except ArithmeticError:
        amount = ""
    return " · ".join(x for x in (params.get("title", ""), amount, day) if x)


def _expense_claim(params: dict) -> tuple[str, str]:
    return _("%(name)s claims an expense") % params, _expense_detail(params)


def _expense_approved(params: dict) -> tuple[str, str]:
    return _("Expense approved"), _with_note(_expense_detail(params), params)


def _expense_rejected(params: dict) -> tuple[str, str]:
    return _("Expense not approved"), _with_note(_expense_detail(params), params)


def _expense_paid(params: dict) -> tuple[str, str]:
    return _("Expense paid"), _with_note(_expense_detail(params), params, "payment_note")


def _expense_cancelled(params: dict) -> tuple[str, str]:
    return _("Expense claim cancelled: %(name)s") % params, _expense_detail(params)


def _goal_progress(params: dict) -> str:
    unit = f" {params['unit']}" if params.get("unit") else ""
    return f"{params.get('title', '')} · {params.get('current', 0)}/{params.get('target', 0)}{unit}"


def _goal_week(params: dict) -> str:
    from datetime import date

    try:
        return _("Week of %(date)s") % {"date": date.fromisoformat(params.get("week", "")).strftime("%d/%m/%Y")}
    except ValueError:
        return ""


def _goal_assigned(params: dict) -> tuple[str, str]:
    return _("New weekly goal for you"), f"{_goal_progress(params)} · {_goal_week(params)}"


def _goal_done(params: dict) -> tuple[str, str]:
    return _("Goal reached: %(title)s") % params, f"{_goal_progress(params)} · {_goal_week(params)}"


def _goal_reminder(params: dict) -> tuple[str, str]:
    from django.utils.dateparse import parse_datetime

    from apps.core.office_time import clock

    closes = parse_datetime(params.get("closes", "") or "")
    count = int(params.get("count", 0) or 0)
    titles = ", ".join(params.get("titles") or [])
    body = ngettext(
        "%(count)s of your goals for this week isn't done yet: %(titles)s. The office closes at %(time)s today.",
        "%(count)s of your goals for this week aren't done yet: %(titles)s. The office closes at %(time)s today.",
        count,
    ) % {"count": count, "titles": titles, "time": clock(closes) if closes else ""}
    return _("This week's goals"), body


def _vendor_added(params: dict) -> tuple[str, str]:
    from django.utils import translation

    urdu = (translation.get_language() or "").startswith("ur")
    categories = params.get("categories_ur" if urdu else "categories") or []
    detail = " · ".join(x for x in (", ".join(categories), params.get("city", "")) if x)
    return _("New vendor: %(name)s") % {"name": params.get("name", "")}, detail


def _visit_detail(params: dict) -> str:
    """ "Clifton Retail · 16/10/2026 2:30 pm–3:30 pm · Main Boulevard, Lahore" (office time, the reader's clock)."""
    when = _event_when({"start": params.get("start"), "end": params.get("end")})
    return " · ".join(x for x in (params.get("place", ""), when, params.get("address", "")) if x)


def _visit_assigned(params: dict) -> tuple[str, str]:
    return _("Field visit: %(title)s") % params, _visit_detail(params)


def _visit_changed(params: dict) -> tuple[str, str]:
    return _("Visit changed: %(title)s") % params, _visit_detail(params)


def _visit_cancelled(params: dict) -> tuple[str, str]:
    return _("Visit cancelled: %(title)s") % params, _with_note(_visit_detail(params), params)


def _visit_request(params: dict) -> tuple[str, str]:
    return _("%(name)s plans a field visit") % params, _visit_detail(params)


def _visit_approved(params: dict) -> tuple[str, str]:
    return _("Visit approved: %(title)s") % params, _with_note(_visit_detail(params), params)


def _visit_rejected(params: dict) -> tuple[str, str]:
    return _("Visit not approved: %(title)s") % params, _with_note(_visit_detail(params), params)


def _visit_done(params: dict) -> tuple[str, str]:
    return _("Visit done: %(title)s") % params, _with_note(_visit_detail(params), params)


def _visit_reminder(params: dict) -> tuple[str, str]:
    return _("Visit in 30 minutes: %(title)s") % params, _visit_detail(params)


def _visit_check_time(params: dict) -> str:
    from django.utils.dateparse import parse_datetime

    from apps.core.office_time import clock

    at = parse_datetime(params.get("at", "") or "")
    return clock(at) if at else ""


def _visit_checked_in(params: dict) -> tuple[str, str]:
    return _("%(person)s arrived: %(title)s") % params, _("Checked in at %(time)s.") % {"time": _visit_check_time(params)} + "\n" + _visit_detail(params)


def _visit_checked_out(params: dict) -> tuple[str, str]:
    return _("%(person)s left: %(title)s") % params, _("Checked out at %(time)s.") % {"time": _visit_check_time(params)} + "\n" + _visit_detail(params)


def _visit_check_in_missed(params: dict) -> tuple[str, str]:
    return _("No check-in yet: %(title)s") % params, _visit_detail(params)


def _visit_reported(params: dict) -> tuple[str, str]:
    """ "Visit report: Quarterly review" / "Outcome: Needs follow-up. Next: send the quote by 20/10/2026." """
    from datetime import date

    from apps.visits.models import VisitReport

    try:
        outcome = VisitReport.Outcome(params.get("outcome")).label
    except ValueError:
        outcome = params.get("outcome", "")
    body = _("%(actor)s wrote the report. Outcome: %(outcome)s.") % {"actor": params.get("actor", ""), "outcome": outcome}
    if params.get("next_action"):
        if params.get("next_action_on"):
            day = date.fromisoformat(params["next_action_on"]).strftime("%d/%m/%Y")
            body += "\n" + _("Next: %(action)s by %(date)s.") % {"action": params["next_action"], "date": day}
        else:
            body += "\n" + _("Next: %(action)s.") % {"action": params["next_action"]}
    return _("Visit report: %(title)s") % params, body + "\n" + _visit_detail(params)


def _errand_detail(params: dict) -> str:
    """ "Bank visit · Bank Alfalah, Gulberg · by 18/10/2026 2:30 pm · Main Boulevard" (office time, the reader's clock)."""
    from django.utils.dateparse import parse_datetime

    from apps.core.office_time import clock, office_tz
    from apps.errands.models import Errand

    try:
        kind = Errand.Kind(params.get("kind")).label
    except ValueError:
        kind = ""
    due = parse_datetime(params.get("due") or "")
    when = _("by %(time)s") % {"time": f"{due.astimezone(office_tz()):%d/%m/%Y} {clock(due)}"} if due else ""
    return " · ".join(str(x) for x in (kind, params.get("place", ""), when, params.get("address", "")) if x)


def _errand_assigned(params: dict) -> tuple[str, str]:
    return _("Errand for you: %(title)s") % params, _("%(actor)s asked you to do it.") % params + "\n" + _errand_detail(params)


def _errand_open(params: dict) -> tuple[str, str]:
    return _("Errand waiting for someone: %(title)s") % params, _("%(actor)s asked for it; nobody has it yet.") % params + "\n" + _errand_detail(params)


def _errand_changed(params: dict) -> tuple[str, str]:
    return _("Errand changed: %(title)s") % params, _errand_detail(params)


def _errand_reassigned(params: dict) -> tuple[str, str]:
    return _("Errand no longer yours: %(title)s") % params, _("%(actor)s gave it to someone else.") % params


def _errand_taken(params: dict) -> tuple[str, str]:
    return _("%(actor)s will do it: %(title)s") % params, _errand_detail(params)


def _errand_started(params: dict) -> tuple[str, str]:
    return _("On the way: %(title)s") % params, _("%(actor)s is on the way.") % params + "\n" + _errand_detail(params)


def _errand_done(params: dict) -> tuple[str, str]:
    body = _("%(actor)s finished it.") % params
    if params.get("reference"):
        body += "\n" + _("Reference: %(reference)s") % params
    return _("Errand done: %(title)s") % params, _with_note(body, params)


def _errand_failed(params: dict) -> tuple[str, str]:
    return _("Errand not done: %(title)s") % params, _with_note(_("%(actor)s couldn't do it.") % params, params)


def _errand_cancelled(params: dict) -> tuple[str, str]:
    return _("Errand cancelled: %(title)s") % params, _with_note(_errand_detail(params), params)


def _errand_due(params: dict) -> tuple[str, str]:
    return _("Errand due soon: %(title)s") % params, _errand_detail(params)


RENDERERS = {
    "visit_checked_in": _visit_checked_in,
    "visit_checked_out": _visit_checked_out,
    "visit_check_in_missed": _visit_check_in_missed,
    "visit_reported": _visit_reported,
    "errand_assigned": _errand_assigned,
    "errand_open": _errand_open,
    "errand_changed": _errand_changed,
    "errand_reassigned": _errand_reassigned,
    "errand_taken": _errand_taken,
    "errand_started": _errand_started,
    "errand_done": _errand_done,
    "errand_failed": _errand_failed,
    "errand_cancelled": _errand_cancelled,
    "errand_due": _errand_due,
    "visit_assigned": _visit_assigned,
    "visit_changed": _visit_changed,
    "visit_cancelled": _visit_cancelled,
    "visit_request": _visit_request,
    "visit_approved": _visit_approved,
    "visit_rejected": _visit_rejected,
    "visit_done": _visit_done,
    "visit_reminder": _visit_reminder,
    "vendor_added": _vendor_added,
    "goal_assigned": _goal_assigned,
    "goal_done": _goal_done,
    "goal_reminder": _goal_reminder,
    "low_stock": _low_stock,
    "purchase_request": _purchase_request,
    "purchase_approved": _purchase_approved,
    "purchase_rejected": _purchase_rejected,
    "purchase_received": _purchase_received,
    "purchase_cancelled": _purchase_cancelled,
    "expense_claim": _expense_claim,
    "expense_approved": _expense_approved,
    "expense_rejected": _expense_rejected,
    "expense_paid": _expense_paid,
    "expense_cancelled": _expense_cancelled,
    "attendance_check_in": _attendance_check_in,
    "attendance_check_out": _attendance_check_out,
    "attendance_corrected": _attendance_corrected,
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
