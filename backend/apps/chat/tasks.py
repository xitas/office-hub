"""Celery jobs for chat (scheduled by Celery Beat; see migration 0004_dm_email_schedule)."""
from celery import shared_task

from . import services


@shared_task
def send_unread_dm_emails() -> int:
    """Every 5 minutes: email direct messages left unread for 30 minutes (each message at most once)."""
    return services.send_unread_dm_emails()
