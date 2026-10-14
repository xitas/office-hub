"""Earlier "Updated own profile" entries that only changed display preferences (theme, language, clock,
reminder timing) get the new description, so the dashboard's team activity leaves them out too."""
from django.db import migrations

PREFERENCES = {"language", "theme", "time_format", "task_reminder_lead"}


def relabel(apps, schema_editor):
    AuditLog = apps.get_model("core", "AuditLog")
    ids = [
        e.pk
        for e in AuditLog.objects.filter(description="Updated own profile").only("pk", "changes").iterator()
        if e.changes and set(e.changes) <= PREFERENCES
    ]
    AuditLog.objects.filter(pk__in=ids).update(description="Changed display preferences")


def unlabel(apps, schema_editor):
    apps.get_model("core", "AuditLog").objects.filter(description="Changed display preferences").update(description="Updated own profile")


class Migration(migrations.Migration):
    dependencies = [("core", "0006_organizationsettings_time_format")]

    operations = [migrations.RunPython(relabel, unlabel)]
