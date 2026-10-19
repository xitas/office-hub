from django.db import migrations

SCHEDULES = [("Errand reminders", "apps.errands.tasks.send_errand_reminders", 5, "minutes")]


def add_schedules(apps, schema_editor):
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    for name, task, every, period in SCHEDULES:
        interval, _ = IntervalSchedule.objects.get_or_create(every=every, period=period)
        PeriodicTask.objects.update_or_create(name=name, defaults={"task": task, "interval": interval, "enabled": True})


def remove_schedules(apps, schema_editor):
    apps.get_model("django_celery_beat", "PeriodicTask").objects.filter(name__in=[s[0] for s in SCHEDULES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("errands", "0001_initial"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [migrations.RunPython(add_schedules, remove_schedules)]
