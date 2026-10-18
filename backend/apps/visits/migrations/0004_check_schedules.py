from django.db import migrations

SCHEDULES = [
    ("Visit check-in reminders", "apps.visits.tasks.send_visit_check_in_reminders", 5, "minutes"),
    ("Remove old visit locations", "apps.visits.tasks.remove_old_visit_locations", 1, "days"),
]


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
        ("visits", "0003_visit_check_in_reminded_start_visitcheck"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [migrations.RunPython(add_schedules, remove_schedules)]
