from django.apps import AppConfig


class TimelineConfig(AppConfig):
    name = "apps.timeline"
    label = "timeline"

    def ready(self):
        from apps.dashboard import registry as dashboard

        from . import builtin  # noqa: F401  registers the built-in entry types and automatic entries
        from django.db.models.signals import post_save

        from apps.tasks.models import Task

        from . import follow_ups
        from .widgets import client_activity, follow_ups_due

        dashboard.register("client_activity", client_activity)
        dashboard.register("follow_ups_due", follow_ups_due)
        # Completing (or reopening) a follow-up task updates its timeline entry.
        post_save.connect(follow_ups.task_saved, sender=Task, dispatch_uid="timeline.follow_up_task_saved")
