"""A report as a document for export: a title, a few header lines and tables, in the reader's language.

Both the PDF and the Excel export are built from this, so they always show the same numbers as the screen (the same
report functions make the data). Dates follow the office's date format; times the reader's clock (12/24-hour).
"""
from dataclasses import dataclass, field
from datetime import date, datetime

from django.utils import timezone, translation
from django.utils.translation import gettext as _

from apps.core.models import OrganizationSettings
from apps.core.office_time import office_tz, urdu_day_period
from apps.tasks.models import Task

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass
class Column:
    label: str
    kind: str = "text"  # text | int | pct (a 0–1 fraction or None) | date (a date or None)
    width: float = 1.0  # relative width in the PDF


@dataclass
class Table:
    title: str
    columns: list[Column]
    rows: list[list]
    note: str = ""


@dataclass
class Document:
    title: str
    lines: list[str]
    tables: list[Table] = field(default_factory=list)
    rtl: bool = False


def fmt_date(d: date | None) -> str:
    if d is None:
        return ""
    style = OrganizationSettings.cached().date_format
    if style == "MM/DD/YYYY":
        return f"{d:%m/%d/%Y}"
    if style == "YYYY-MM-DD":
        return d.isoformat()
    if style == "DD MMM YYYY":
        return f"{d.day:02d} {MONTHS[d.month - 1]} {d.year}"
    return f"{d:%d/%m/%Y}"


def fmt_time(user, moment: datetime) -> str:
    """The reader's clock: their own 12/24-hour choice, else the office's."""
    t = moment.astimezone(office_tz())
    if (user.time_format or OrganizationSettings.cached().time_format) == "24h":
        return f"{t:%H:%M}"
    hour = t.hour % 12 or 12
    if (translation.get_language() or "").startswith("ur"):
        return f"{urdu_day_period(t.hour)} {hour}:{t.minute:02d}"
    return f"{hour}:{t.minute:02d} {'am' if t.hour < 12 else 'pm'}"


def _header(user, scope, period_line: str) -> list[str]:
    who = scope.person.full_name if scope.person else scope.department.name if scope.department else _("Everyone")
    now = timezone.now()
    return [
        period_line,
        _("Covers: %(who)s") % {"who": who},
        _("Made %(date)s %(time)s by %(name)s") % {"date": fmt_date(now.astimezone(office_tz()).date()), "time": fmt_time(user, now),
                                                   "name": user.full_name},
    ]


def _rtl() -> bool:
    return (translation.get_language() or "").startswith("ur")


def completion_document(data, scope, user) -> Document:
    def cols(first_label):
        return [
            Column(first_label, "text", 2.4), Column(_("Due"), "int"), Column(_("Done"), "int"), Column(_("On time"), "int"),
            Column(_("Late"), "int"), Column(_("Overdue"), "int"), Column(_("Still open"), "int"), Column(_("Completion rate"), "pct", 1.2),
            Column(_("On time rate"), "pct", 1.2), Column(_("Completed in the period"), "int", 1.2),
        ]

    def cells(r):
        return [r["due"], r["done"], r["on_time"], r["late"], r["overdue"], r["open"], r["rate"], r["on_time_rate"], r["completed"]]

    t = data["totals"]
    return Document(
        title=_("Task completion"),
        lines=_header(user, scope, _("Tasks due %(first)s – %(last)s") % {"first": fmt_date(data["from"]), "last": fmt_date(data["to"])}),
        tables=[
            Table(_("Overall"), cols(""), [[_("All"), *cells(t)]]),
            Table(_("By department"), cols(_("Department")), [[d["name"] or _("No department"), *cells(d)] for d in data["departments"]]),
            Table(_("By person"), [cols(_("Person"))[0], Column(_("Department"), "text", 1.6), *cols("")[1:]],
                  [[p["name"], p["department"] or "", *cells(p)] for p in data["people"]]),
        ],
        rtl=_rtl(),
    )


def overdue_document(data, scope, user) -> Document:
    priorities = dict(Task.Priority.choices)
    people = Table(
        _("By person"),
        [Column(_("Person"), "text", 2.2), Column(_("Department"), "text", 1.6), Column(_("Overdue"), "int"), Column(_("1–7 days late"), "int", 1.2),
         Column(_("8–30 days late"), "int", 1.2), Column(_("Over 30 days late"), "int", 1.2), Column(_("High or urgent"), "int", 1.2),
         Column(_("Oldest due date"), "date", 1.4)],
        [[p["name"], p["department"] or "", p["overdue"], p["days_1_7"], p["days_8_30"], p["days_31_plus"], p["urgent"], p["oldest"]]
         for p in data["people"]],
    )
    shown = len(data["tasks"])
    tasks = Table(
        _("Overdue tasks"),
        [Column(_("Task"), "text", 3), Column(_("Due date"), "date", 1.3), Column(_("Days late"), "int"), Column(_("Priority"), "text"),
         Column(_("Assigned to"), "text", 2), Column(_("Contact or company"), "text", 1.8)],
        [[t["title"], t["due_date"], t["days_late"], str(priorities.get(t["priority"], t["priority"])), ", ".join(t["assignees"]),
          t["record"] or ""] for t in data["tasks"]],
        note=_("The %(shown)s most overdue of %(total)s.") % {"shown": shown, "total": data["total"]} if data["total"] > shown else "",
    )
    return Document(
        title=_("Overdue tasks"),
        lines=_header(user, scope, _("As of %(date)s") % {"date": fmt_date(data["as_of"])}),
        tables=[people, tasks],
        rtl=_rtl(),
    )


# ================================================================ client reports


def _kind_label(kind) -> str:
    from apps.timeline import registry

    entry_type = registry.get_type(kind)
    return str(entry_type.label) if entry_type else kind


def bucket_label(row, by) -> str:
    """ "October 2026" for a month, "05/10/2026 – 11/10/2026" for a week (clipped to the period)."""
    from django.utils.dates import MONTHS as MONTH_NAMES

    if by == "month":
        return f"{MONTH_NAMES[row['from'].month]} {row['from'].year}"
    return f"{fmt_date(row['from'])} – {fmt_date(row['to'])}"


def interactions_document(data, scope, user) -> Document:
    kinds = data["kinds"]
    kind_cols = [Column(_kind_label(k), "int") for k in kinds]
    period = Table(
        _("By month") if data["by"] == "month" else _("By week"),
        [Column(_("Month") if data["by"] == "month" else _("Week"), "text", 2.2), *kind_cols, Column(_("Total"), "int")],
        [[bucket_label(r, data["by"]), *[r["counts"][k] for k in kinds], r["total"]] for r in data["buckets"]]
        + [[_("Total"), *[data["totals"]["counts"][k] for k in kinds], data["totals"]["total"]]],
    )
    people = Table(
        _("By person"),
        [Column(_("Person"), "text", 2.2), Column(_("Department"), "text", 1.6), *kind_cols, Column(_("Total"), "int"),
         Column(_("Clients reached"), "int", 1.2)],
        [[p["name"], p["department"] or "", *[p["counts"][k] for k in kinds], p["total"], p["clients"]] for p in data["people"]],
        note=_("Calls, meetings, emails, WhatsApp messages and visit reports logged on contacts and companies; notes are internal and not counted."),
    )
    return Document(
        title=_("Client interactions"),
        lines=_header(user, scope, _("%(first)s – %(last)s") % {"first": fmt_date(data["from"]), "last": fmt_date(data["to"])}),
        tables=[period, people],
        rtl=_rtl(),
    )


def pipeline_document(data, scope, user) -> Document:
    from apps.contacts.models import Contact

    statuses = dict(Contact.Status.choices)

    def cols(first):
        return [first, Column(_("New leads"), "int"), Column(_("Reached Contacted"), "int", 1.2), Column(_("Reached In discussion"), "int", 1.3),
                Column(_("Won"), "int"), Column(_("Lost"), "int"), Column(_("Still open"), "int"), Column(_("Win rate"), "pct"),
                Column(_("Conversion"), "pct")]

    def cells(r):
        return [r["created"], r["contacted"], r["in_discussion"], r["won"], r["lost"], r["open"], r["win_rate"], r["conversion"]]

    f = data["funnel"]
    days = data["average_days_to_win"]
    return Document(
        title=_("Lead pipeline"),
        lines=_header(user, scope, _("Leads added %(first)s – %(last)s") % {"first": fmt_date(data["from"]), "last": fmt_date(data["to"])}),
        tables=[
            Table(_("Leads added in the period"), cols(Column("", "text", 1.6)), [[_("All"), *cells(f)]],
                  note=_("Win rate: won out of those closed (won or lost). Conversion: won out of all leads added.")),
            Table(_("By person"), cols(Column(_("Person"), "text", 2.2)),
                  [[p["name"] or _("Unassigned"), *cells(p)] for p in data["people"]]),
            Table(_("Status changes in the period"), [Column(_("From"), "text", 1.5), Column(_("To"), "text", 1.5), Column(_("Changes"), "int")],
                  [[str(statuses.get(m["from"], m["from"])), str(statuses.get(m["to"], m["to"])), m["count"]] for m in data["moves"]],
                  note=_("Won in the period: %(n)s; on average %(days)s days after the lead was added.") % {
                      "n": data["won_in_period"], "days": "—" if days is None else f"{days:g}"}),
        ],
        rtl=_rtl(),
    )


# ================================================================ field reports


def field_visits_document(data, scope, user) -> Document:
    from apps.visits.models import Visit, VisitReport

    purposes = dict(Visit.Purpose.choices)
    outcomes = dict(VisitReport.Outcome.choices)

    def cols(first):
        return [first, Column(_("Scheduled"), "int"), Column(_("Done"), "int"), Column(_("Cancelled"), "int"), Column(_("Not closed"), "int"),
                Column(_("Upcoming"), "int"), Column(_("Completion rate"), "pct", 1.2), Column(_("Checked in"), "int"),
                Column(_("With a report"), "int", 1.1)]

    def cells(r):
        return [r["scheduled"], r["done"], r["cancelled"], r["not_closed"], r["upcoming"], r["completion"], r["checked_in"], r["reported"]]

    return Document(
        title=_("Field visits"),
        lines=_header(user, scope, _("Visits %(first)s – %(last)s") % {"first": fmt_date(data["from"]), "last": fmt_date(data["to"])}),
        tables=[
            Table(_("Overall"), cols(Column("", "text", 1.6)), [[_("All"), *cells(data["totals"])]],
                  note=_("Completion rate: done out of the visits whose time has come (done, cancelled or not closed).")),
            Table(_("By person"), cols(Column(_("Person"), "text", 2.2)), [[p["name"], *cells(p)] for p in data["people"]]),
            Table(_("By purpose"), cols(Column(_("Purpose"), "text", 2.2)), [[str(purposes.get(r["purpose"], r["purpose"])), *cells(r)] for r in data["purposes"]]),
            Table(_("Report outcomes"), [Column(_("Outcome"), "text", 2), Column(_("Reports"), "int"), Column(_("Share"), "pct")],
                  [[str(outcomes.get(o["outcome"], o["outcome"])), o["count"], o["share"]] for o in data["outcomes"]]),
        ],
        rtl=_rtl(),
    )


def errands_document(data, scope, user) -> Document:
    from apps.errands.models import Errand

    kinds = dict(Errand.Kind.choices)

    def cols(first):
        return [first, Column(_("Asked for"), "int"), Column(_("Done"), "int"), Column(_("Not done"), "int"), Column(_("Cancelled"), "int"),
                Column(_("Still open"), "int"), Column(_("Overdue"), "int"), Column(_("Success rate"), "pct", 1.1),
                Column(_("Done on time"), "pct", 1.1)]

    def cells(r):
        return [r["asked"], r["done"], r["failed"], r["cancelled"], r["open"], r["overdue"], r["success"], r["on_time_rate"]]

    return Document(
        title=_("Errands"),
        lines=_header(user, scope, _("Errands due %(first)s – %(last)s") % {"first": fmt_date(data["from"]), "last": fmt_date(data["to"])}),
        tables=[
            Table(_("Overall"), cols(Column("", "text", 1.6)), [[_("All"), *cells(data["totals"])]],
                  note=_("Success rate: done out of done or not done. Done on time: finished by the time it was due.")),
            Table(_("By person"), cols(Column(_("Person"), "text", 2.2)), [[p["name"] or _("Nobody yet"), *cells(p)] for p in data["people"]]),
            Table(_("By kind"), cols(Column(_("Kind"), "text", 2.2)), [[str(kinds.get(r["kind"], r["kind"])), *cells(r)] for r in data["kinds"]]),
        ],
        rtl=_rtl(),
    )
