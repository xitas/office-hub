"""Follow-ups on logged communications become tasks.

When an entry is saved with a follow-up date, a task due that day is created automatically,
linked to the same contact or company and to the entry (Task.follow_up_of), and assigned to the
person who logged it, or to a colleague they choose (same assignment rules as any task). They can
also skip it ("no task"). Completing the task marks the follow-up done on the entry; reopening the
task clears that again. Changing the follow-up date moves an open task's due date with it.
"""
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from rest_framework.exceptions import ValidationError

from apps.core.permissions import has_perm

TITLE_LENGTH = 200


def task_title(entry) -> str:
    target = entry.contact.full_name if entry.contact else entry.company.name
    first_line = (entry.summary or "").strip().split("\n")[0].strip()
    title = _("Follow up with %(name)s") % {"name": target}
    if first_line:
        title += f": {first_line}"
    return title[:TITLE_LENGTH]


def check_assignee(user, assignee):
    """The person a follow-up task may go to: yourself, or someone you may assign tasks to."""
    from apps.accounts.models import User
    from apps.tasks.rules import assignable_users

    if assignee is None or assignee.pk == user.pk:
        return user
    if not assignable_users(user, User.objects.filter(pk=assignee.pk, is_active=True)).exists():
        raise ValidationError({"follow_up_assignee": [
            _("You can only assign tasks to yourself and people in your department.") if user.department_id
            else _("You can only assign tasks to yourself.")
        ]})
    return assignee


@transaction.atomic
def sync(entry, user, *, assignee=None, skip=False, date_changed=True, request=None):
    """Create, move or skip the follow-up task after an entry is saved. Returns the task (or None)."""
    from apps.core.audit import log_action, snapshot
    from apps.core.models import AuditLog
    from apps.tasks import schedule
    from apps.tasks.collab import record
    from apps.tasks.models import Task

    if not entry.follow_up_on:
        return None
    task = entry.follow_up_tasks.order_by("-pk").first()
    if task is not None:
        if task.status != Task.Status.DONE and task.due_date != entry.follow_up_on:
            old = task.due_date
            task.due_date = entry.follow_up_on
            task.save(update_fields=["due_date", "updated_at"])
            record(task, user, "due", old=old.isoformat() if old else None, new=task.due_date.isoformat(), old_time=None, new_time=None)
        return task
    if not date_changed:
        return None  # e.g. editing the text of an entry whose follow-up was skipped
    if skip:
        if not entry.follow_up_skipped:
            entry.follow_up_skipped = True
            entry.save(update_fields=["follow_up_skipped"])
        return None
    if not has_perm(user, "tasks", "create"):
        return None
    person = check_assignee(user, assignee)
    task = Task.objects.create(
        title=task_title(entry), description=entry.summary, due_date=entry.follow_up_on,
        contact=entry.contact, company=entry.company, follow_up_of=entry, created_by=user, updated_by=user,
    )
    task.assignees.set([person])
    if entry.follow_up_skipped:
        entry.follow_up_skipped = False
        entry.save(update_fields=["follow_up_skipped"])
    record(task, user, "created")
    log_action(user, AuditLog.Action.CREATE, task, changes={**snapshot(task), "assignees": person.full_name}, request=request)
    schedule.notify_assigned(task, [person], user)
    return task


def task_saved(sender, instance, **kwargs):
    """Completing a follow-up task marks the follow-up done on its entry; reopening clears it."""
    if not instance.follow_up_of_id:
        return
    from .models import TimelineEntry

    done = instance.status == instance.Status.DONE
    entries = TimelineEntry.objects.filter(pk=instance.follow_up_of_id)
    if done:
        entries.filter(follow_up_done_at__isnull=True).update(follow_up_done_at=instance.completed_at or timezone.now())
    else:
        entries.filter(follow_up_done_at__isnull=False).update(follow_up_done_at=None)
