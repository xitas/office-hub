from django.db import transaction

from .tasks import send_email


def queue_email(subject: str, body: str, recipients: list[str]) -> None:
    """Send email via Celery once the surrounding transaction commits (immediately if none).

    With Redis configured, a worker sends it in the background; without a broker
    (local dev/tests) the task runs inline.
    """
    subject, body, recipients = str(subject), str(body), list(recipients)
    transaction.on_commit(lambda: send_email.delay(subject, body, recipients))
