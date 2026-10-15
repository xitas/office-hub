"""Celery jobs for attendance (scheduled by Celery Beat; see migration 0002_reminder_schedule)."""
from celery import shared_task

from . import services


@shared_task
def send_attendance_reminders() -> dict:
    """Every 5 minutes: "forgot to check in / out?" reminders (each once a day per person)."""
    return services.send_reminders()
