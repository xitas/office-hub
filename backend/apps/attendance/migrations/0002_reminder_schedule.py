from django.db import migrations

NAME = "Attendance reminders"


def add_schedule(apps, schema_editor):
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    every, _ = IntervalSchedule.objects.get_or_create(every=5, period="minutes")
    PeriodicTask.objects.update_or_create(
        name=NAME, defaults={"task": "apps.attendance.tasks.send_attendance_reminders", "interval": every, "enabled": True}
    )


def remove_schedule(apps, schema_editor):
    apps.get_model("django_celery_beat", "PeriodicTask").objects.filter(name=NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0001_initial"),
        ("django_celery_beat", "0019_alter_periodictasks_options"),
    ]

    operations = [migrations.RunPython(add_schedule, remove_schedule)]
