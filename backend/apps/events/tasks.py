"""Celery jobs for the calendar (scheduled by Celery Beat; see migration 0002_reminder_schedule)."""
from celery import shared_task

from . import services


@shared_task
def send_meeting_reminders() -> int:
    """Every minute: remind people of meetings starting within 15 minutes (each start time once)."""
    return services.send_reminders()
