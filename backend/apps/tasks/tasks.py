"""Celery jobs for tasks (scheduled by Celery Beat; see migration 0004_reminder_schedules)."""
from celery import shared_task

from . import schedule


@shared_task
def send_task_reminders() -> dict:
    """Every 5 minutes: "due soon" and "overdue" notices (each sent once, see schedule.py)."""
    return {"due_soon": schedule.send_due_soon(), "overdue": schedule.send_overdue()}


@shared_task
def send_daily_digests() -> int:
    """Every 15 minutes: the 9:00 office-time digest for everyone who hasn't had today's yet."""
    return schedule.send_digests()


@shared_task
def create_recurring_tasks() -> int:
    """Every 30 minutes: next occurrence for repeating tasks whose current one is past due."""
    return schedule.generate_due_occurrences()
