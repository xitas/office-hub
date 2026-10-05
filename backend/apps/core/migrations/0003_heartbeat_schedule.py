"""Register the Celery Beat heartbeat (every minute) in the database scheduler.

Schedules live in django-celery-beat's tables, so later jobs (deadline reminders,
recurring tasks) can be added the same way or edited in Django admin.
"""
from django.db import migrations

TASK_NAME = "System heartbeat"


def add_schedule(apps, schema_editor):
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    every_minute, _ = IntervalSchedule.objects.get_or_create(every=1, period="minutes")
    PeriodicTask.objects.update_or_create(
        name=TASK_NAME,
        defaults={"task": "apps.core.tasks.heartbeat", "interval": every_minute, "enabled": True},
    )


def remove_schedule(apps, schema_editor):
    apps.get_model("django_celery_beat", "PeriodicTask").objects.filter(name=TASK_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_alter_auditlog_options_alter_auditlog_action"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [migrations.RunPython(add_schedule, remove_schedule)]
