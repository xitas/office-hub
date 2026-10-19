"""Who and when a report covers.

- Reports are for managers (their own department) and admins (everyone, or one department). Every number comes
  from data the viewer may see: the people in scope, and only tasks visible to the viewer.
- A period is two office dates (inclusive), at most a year and a day apart. The frontend offers presets (this week
  from the office's week start, this month, this quarter, this year…); the API takes the dates.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _
from rest_framework.exceptions import ValidationError

from apps.accounts.models import Department, User
from apps.core.office_time import office_today, office_tz
from apps.leave.rules import is_admin

MAX_DAYS = 366


@dataclass
class Scope:
    people: list  # active users the report covers, with their department
    department: Department | None  # chosen (admins) or the manager's own
    person: User | None


def scope_for(user, params) -> Scope:
    """The people a report covers: a manager's department, or everyone (one department, if chosen) for admins;
    optionally one person among them."""
    qs = User.objects.filter(is_active=True).select_related("department").order_by("full_name")
    department = None
    if is_admin(user):
        if (dept := params.get("department")) and str(dept).isdigit():
            department = Department.objects.filter(pk=int(dept)).first()
            if department is None:
                raise ValidationError({"department": [_("Unknown department.")]})
            qs = qs.filter(department=department)
    else:
        department = user.department
        qs = qs.filter(department_id=user.department_id) if user.department_id else qs.filter(pk=user.pk)
    people = list(qs)
    person = None
    if (pid := params.get("person")) and str(pid).isdigit():
        person = next((p for p in people if p.pk == int(pid)), None)
        if person is None:
            raise ValidationError({"person": [_("This person isn't in the report.")]})
        people = [person]
    return Scope(people=people, department=department, person=person)


def period_for(params) -> tuple[date, date]:
    """from/to (YYYY-MM-DD, inclusive); default: this month so far."""
    today = office_today()
    first = parse_date(params.get("from") or "") or today.replace(day=1)
    last = parse_date(params.get("to") or "") or today
    if last < first:
        raise ValidationError({"to": [_("The end comes before the start.")]})
    if (last - first).days >= MAX_DAYS:
        raise ValidationError({"from": [_("A report covers a year at most.")]})
    return first, last


def day_bounds(first: date, last: date) -> tuple[datetime, datetime]:
    """The moments the office days start and end: [first 00:00, last+1 00:00) in the office time zone."""
    tz = office_tz()
    return datetime.combine(first, time.min, tzinfo=tz), datetime.combine(last + timedelta(days=1), time.min, tzinfo=tz)
