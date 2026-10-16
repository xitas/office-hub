"""Celery jobs for weekly planning (scheduled by Celery Beat; see migration 0002_reminder_schedule)."""
from celery import shared_task

from . import services


@shared_task
def send_goal_reminders() -> int:
    """Every 15 minutes: on the week's last working day, owners of unfinished goals are reminded once."""
    return services.send_reminders()
