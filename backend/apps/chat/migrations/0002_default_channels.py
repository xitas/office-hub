"""General plus one channel per department, with every active user in the right ones."""
from django.db import migrations


def create_default_channels(apps, schema_editor):
    Conversation = apps.get_model("chat", "Conversation")
    Membership = apps.get_model("chat", "Membership")
    Department = apps.get_model("accounts", "Department")
    User = apps.get_model("accounts", "User")

    general, _ = Conversation.objects.get_or_create(
        is_default=True, channel_type="general",
        defaults={"kind": "channel", "name": "General", "description": "Everyone in the office"},
    )
    users = list(User.objects.filter(is_active=True))
    Membership.objects.bulk_create([Membership(conversation=general, user=u) for u in users], ignore_conflicts=True)
    for department in Department.objects.all():
        channel, _ = Conversation.objects.get_or_create(
            is_default=True, channel_type="department", department=department,
            defaults={"kind": "channel", "name": department.name[:80], "is_private": True},
        )
        Membership.objects.bulk_create(
            [Membership(conversation=channel, user=u) for u in users if u.department_id == department.pk], ignore_conflicts=True
        )


class Migration(migrations.Migration):
    dependencies = [("chat", "0001_initial"), ("accounts", "0007_user_task_reminder_lead")]

    operations = [migrations.RunPython(create_default_channels, migrations.RunPython.noop)]
