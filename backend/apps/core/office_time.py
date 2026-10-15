"""Dates in the office's time zone (Organization settings), not the server's.

"Today", "due today" and "overdue" must flip at the office's midnight. Django's TIME_ZONE is only
the default; an admin can set another zone on the Organization page.
"""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.utils import timezone, translation


def office_tz() -> ZoneInfo:
    from .models import OrganizationSettings

    try:
        return ZoneInfo(OrganizationSettings.cached().timezone or settings.TIME_ZONE)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(settings.TIME_ZONE)


def office_now() -> datetime:
    return timezone.now().astimezone(office_tz())


def office_today() -> date:
    return office_now().date()


def clock(moment: datetime | time) -> str:
    """A time of day in the organization's clock format: "2:30 pm" (12-hour) or "14:30" (24-hour),
    in the office time zone. Used in notifications and emails (which go to many people at once)."""
    from .models import OrganizationSettings

    t = moment.astimezone(office_tz()).time() if isinstance(moment, datetime) else moment
    if OrganizationSettings.cached().time_format == "24h":
        return t.strftime("%H:%M")
    hour = t.hour % 12 or 12
    if (translation.get_language() or "").startswith("ur"):
        # Urdu says the part of the day before the time ("صبح 9:00", "شام 5:30"), as in everyday speech and writing.
        return f"{urdu_day_period(t.hour)} {hour}:{t.minute:02d}"
    return f"{hour}:{t.minute:02d} {'am' if t.hour < 12 else 'pm'}"


def urdu_day_period(hour: int) -> str:
    """صبح 5–12, دوپہر 12–16, شام 16–20, رات 20–5 (the same bands the frontend uses)."""
    if 5 <= hour < 12:
        return "صبح"
    if 12 <= hour < 16:
        return "دوپہر"
    if 16 <= hour < 20:
        return "شام"
    return "رات"


def office_datetime(day: date, at: time) -> datetime:
    """An aware moment for a wall-clock date and time in the office."""
    return datetime.combine(day, at, tzinfo=office_tz())
