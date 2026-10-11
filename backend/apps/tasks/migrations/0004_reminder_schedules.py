from django.db import migrations

JOBS = [
    # (name, task, minutes)
    ("Task reminders (due soon, overdue)", "apps.tasks.tasks.send_task_reminders", 5),
    ("Morning task digest", "apps.tasks.tasks.send_daily_digests", 15),
    ("Repeating tasks", "apps.tasks.tasks.create_recurring_tasks", 30),
]


def add_schedules(apps, schema_editor):
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    for name, task, minutes in JOBS:
        every, _ = IntervalSchedule.objects.get_or_create(every=minutes, period="minutes")
        PeriodicTask.objects.update_or_create(name=name, defaults={"task": task, "interval": every, "enabled": True})


def remove_schedules(apps, schema_editor):
    apps.get_model("django_celery_beat", "PeriodicTask").objects.filter(name__in=[j[0] for j in JOBS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0003_task_follow_up_of_taskseries_task_series_digestlog_and_more"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [migrations.RunPython(add_schedules, remove_schedules)]
