"""Follow-ups whose task was already completed count as done."""
from django.db import migrations
from django.db.models import OuterRef, Subquery


def mark_done(apps, schema_editor):
    TimelineEntry = apps.get_model("timeline", "TimelineEntry")
    Task = apps.get_model("tasks", "Task")
    done = Task.objects.filter(follow_up_of=OuterRef("pk"), status="done").order_by("-completed_at").values("completed_at")[:1]
    TimelineEntry.objects.filter(follow_up_tasks__status="done").update(follow_up_done_at=Subquery(done))


class Migration(migrations.Migration):
    dependencies = [("timeline", "0002_follow_up_state"), ("tasks", "0005_task_time_indexes")]

    operations = [migrations.RunPython(mark_done, migrations.RunPython.noop)]
