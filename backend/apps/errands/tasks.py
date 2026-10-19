from celery import shared_task

from . import services


@shared_task
def send_errand_reminders():
    """Errands due within the hour: the runner is reminded once (Celery Beat, every 5 minutes)."""
    return services.send_reminders()
