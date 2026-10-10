"""Dates in the office's time zone (Organization settings), not the server's.

"Today", "due today" and "overdue" must flip at the office's midnight. Django's TIME_ZONE is only
the default; an admin can set another zone on the Organization page.
"""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.utils import timezone


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


def office_datetime(day: date, at: time) -> datetime:
    """An aware moment for a wall-clock date and time in the office."""
    return datetime.combine(day, at, tzinfo=office_tz())
