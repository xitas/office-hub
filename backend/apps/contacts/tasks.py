from celery import shared_task

from .importer import run_import


@shared_task
def run_contact_import(job_id: int) -> int:
    """Large CSV imports run here, so the upload request returns at once and the page shows progress."""
    run_import(job_id)
    return job_id
