"""Celery jobs for field visits (scheduled by Celery Beat; see migration 0002_reminder_schedule)."""
from celery import shared_task

from . import services


@shared_task
def send_visit_reminders() -> int:
    """Every minute: the people going on a visit are reminded 30 minutes before it starts (once per start time)."""
    return services.send_reminders()
