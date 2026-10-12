"""The communication log (all logged calls, meetings, emails, WhatsApp messages and notes) and
"last contacted" dates for contacts and companies.

Visibility is the timeline's: entries on contacts and companies the user can see (staff their own
records, managers their department's, admins all).
"""
from datetime import datetime, time

from django.db.models import DateTimeField, OuterRef, Q, Subquery
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _
from rest_framework.exceptions import ValidationError

from apps.core.office_time import office_tz

from .builtin import CONTACT_KINDS, LOG_KINDS
from .models import TimelineEntry

FOLLOW_UP_FILTERS = ("any", "open", "done", "none")


def _int(params, name):
    value = params.get(name)
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        raise ValidationError({name: _("Give a number.")})


def _date(params, name):
    value = params.get(name)
    if not value:
        return None
    day = parse_date(value)
    if day is None:
        raise ValidationError({name: _("Give a date as YYYY-MM-DD.")})
    return day


def log_queryset(user, params):
    """Logged communications the user can see, newest first, filtered by the query parameters:
    `type` (comma-separated kinds), `direction` (in/out), `logged_by`, `contact`, `company` (also its
    contacts' entries), `date_from` / `date_to` (office dates), `follow_up` (any/open/done/none), `q`."""
    from .views import visible_entries

    qs = visible_entries(user).filter(kind__in=LOG_KINDS)
    kinds = [k for k in params.get("type", "").split(",") if k]
    if kinds:
        unknown = set(kinds) - set(LOG_KINDS)
        if unknown:
            raise ValidationError({"type": _("Unknown entry type.")})
        qs = qs.filter(kind__in=kinds)
    direction = params.get("direction")
    if direction:
        if direction not in ("in", "out"):
            raise ValidationError({"direction": _("Choose in or out.")})
        qs = qs.filter(details__direction=direction)
    if (logged_by := _int(params, "logged_by")) is not None:
        qs = qs.filter(created_by_id=logged_by)
    if (contact := _int(params, "contact")) is not None:
        qs = qs.filter(contact_id=contact)
    if (company := _int(params, "company")) is not None:
        qs = qs.filter(Q(company_id=company) | Q(contact__company_id=company))
    tz = office_tz()
    if (day := _date(params, "date_from")) is not None:
        qs = qs.filter(occurred_at__gte=datetime.combine(day, time.min, tzinfo=tz))
    if (day := _date(params, "date_to")) is not None:
        qs = qs.filter(occurred_at__lte=datetime.combine(day, time.max, tzinfo=tz))
    follow_up = params.get("follow_up") or ("any" if params.get("has_follow_up") in ("1", "true") else "")
    if follow_up:
        if follow_up not in FOLLOW_UP_FILTERS:
            raise ValidationError({"follow_up": _("Choose any, open, done or none.")})
        if follow_up == "none":
            qs = qs.filter(follow_up_on__isnull=True)
        else:
            qs = qs.filter(follow_up_on__isnull=False)
            if follow_up == "open":
                qs = qs.filter(follow_up_done_at__isnull=True)
            elif follow_up == "done":
                qs = qs.filter(follow_up_done_at__isnull=False)
    if q := params.get("q", "").strip():
        qs = qs.filter(Q(summary__icontains=q) | Q(details__subject__icontains=q))
    return qs.prefetch_related("follow_up_tasks__assignees").order_by("-occurred_at", "-id")


# ================================================================ CSV export


def export_log(request, queryset):
    from apps.contacts.csv_io import CsvWriter
    from apps.contacts.transfer import _log_export, csv_response
    from django.utils.translation import gettext_noop

    from . import registry
    from .builtin import CallDetailsSerializer

    directions = dict(CallDetailsSerializer.DIRECTIONS)
    outcomes = dict(CallDetailsSerializer.OUTCOMES)
    writer = CsvWriter(header=[
        _("Date"), _("Type"), _("Direction"), _("Contact"), _("Company"), _("Subject"), _("Summary"), _("Call outcome"),
        _("Logged by"), _("Follow-up date"), _("Follow-up"), _("Follow-up task for"),
    ])
    tz = office_tz()
    count = 0
    for e in queryset.select_related("contact__company", "company", "created_by"):
        entry_type = registry.get_type(e.kind)
        task = next(iter(e.follow_up_tasks.all()), None)
        if not e.follow_up_on:
            follow_up = ""
        elif e.follow_up_done_at:
            follow_up = _("Done")
        elif e.follow_up_skipped and task is None:
            follow_up = _("No task")
        else:
            follow_up = _("Open")
        company = e.company or (e.contact.company if e.contact else None)
        writer.raw_row([
            timezone.localtime(e.occurred_at, tz).strftime("%Y-%m-%d %H:%M"),
            str(entry_type.label) if entry_type else e.kind,
            str(directions.get(e.details.get("direction"), "")),
            e.contact.full_name if e.contact else "",
            company.name if company else "",
            e.details.get("subject", ""),
            e.summary,
            str(outcomes.get(e.details.get("outcome"), "")),
            e.created_by.full_name if e.created_by else "",
            e.follow_up_on.isoformat() if e.follow_up_on else "",
            follow_up,
            ", ".join(sorted(u.full_name for u in task.assignees.all())) if task else "",
        ])
        count += 1
    _log_export(request, "communication log", count, gettext_noop("Exported the communication log to a CSV file"))
    return csv_response(writer.getvalue(), f"communication-log-{timezone.localdate():%Y-%m-%d}.csv")


# ================================================================ last contacted


def with_last_contacted_contacts(qs):
    """`last_contacted_at`: the latest call, meeting, email or WhatsApp logged on the contact."""
    latest = TimelineEntry.objects.filter(contact=OuterRef("pk"), kind__in=CONTACT_KINDS).order_by("-occurred_at").values("occurred_at")[:1]
    return qs.annotate(last_contacted_at=Subquery(latest, output_field=DateTimeField()))


def with_last_contacted_companies(qs):
    """`last_contacted_at` for companies: on the company itself or any of its contacts."""
    latest = (
        TimelineEntry.objects.filter(Q(company=OuterRef("pk")) | Q(contact__company=OuterRef("pk")), kind__in=CONTACT_KINDS)
        .order_by("-occurred_at")
        .values("occurred_at")[:1]
    )
    return qs.annotate(last_contacted_at=Subquery(latest, output_field=DateTimeField()))
