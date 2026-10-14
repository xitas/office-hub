"""Celery jobs for bookings (scheduled by Celery Beat; see migration 0003_reminder_schedule)."""
from celery import shared_task

from . import services


@shared_task
def send_booking_reminders() -> int:
    """Every minute: remind people of bookings starting within 15 minutes (each start time once)."""
    return services.send_reminders()
