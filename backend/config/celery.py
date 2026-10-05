"""Celery application. Start a worker on Windows with:  celery -A config worker --pool=solo -l info
and the scheduler with:  celery -A config beat -l info   (schedules are stored in the database)."""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("office_crm")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
