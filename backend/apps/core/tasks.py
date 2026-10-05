import logging
import smtplib
import time

from celery import shared_task
from django.core.cache import cache
from django.core.mail import send_mail

logger = logging.getLogger(__name__)

HEARTBEAT_CACHE_KEY = "health:celery:heartbeat"


@shared_task(
    autoretry_for=(smtplib.SMTPException, ConnectionError, OSError),
    retry_backoff=30,  # 30s, 60s, 120s, ...
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
)
def send_email(subject: str, body: str, recipients: list[str]) -> int:
    """Send one email from a worker, so slow or failing SMTP never delays a web request."""
    return send_mail(subject, body, None, recipients, fail_silently=False)


@shared_task
def heartbeat() -> float:
    """Scheduled every minute by Celery Beat. Its timestamp proves broker, beat and worker all run."""
    now = time.time()
    cache.set(HEARTBEAT_CACHE_KEY, now, timeout=60 * 60)
    return now
