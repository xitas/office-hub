"""Celery jobs for field visits (scheduled by Celery Beat; see migration 0002_reminder_schedule)."""
from celery import shared_task

from . import services


@shared_task
def send_visit_reminders() -> int:
    """Every minute: the people going on a visit are reminded 30 minutes before it starts (once per start time)."""
    return services.send_reminders()


@shared_task
def send_visit_check_in_reminders() -> int:
    """Every 5 minutes: "no check-in yet" to the person responsible, 30 minutes after a planned visit started (once)."""
    from . import checks

    return checks.send_missed_check_in()


@shared_task
def remove_old_visit_locations() -> int:
    """Daily: check-in and check-out coordinates older than 90 days are removed (times and visits stay)."""
    from . import checks

    return checks.remove_old_locations()
