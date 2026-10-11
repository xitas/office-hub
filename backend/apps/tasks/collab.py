"""Checklist, comments, mentions and attachments: who may do what, the activity trail and notifications."""
import re

from django.db.models import Q

from apps.accounts.models import User
from apps.core.permissions import ADMIN, MANAGER, has_perm

from .models import TaskActivity

# @[Full Name](user:12) — written by the mention picker; the id is what counts.
MENTION_RE = re.compile(r"@\[([^\]\n]{1,150})\]\(user:(\d+)\)")


def people_who_can_see(task):
    """Active users who can open this task (same rules as rules.visible_tasks, seen from the task's side)."""
    assignees = list(task.assignees.all())
    departments = {u.department_id for u in [*assignees, task.created_by] if u and u.department_id}
    return User.objects.filter(is_active=True).filter(
        Q(role=ADMIN)
        | Q(is_superuser=True)
        | Q(pk=task.created_by_id)
        | Q(pk__in=[u.pk for u in assignees])
        | Q(role=MANAGER, department_id__in=departments)
    ).distinct()


def mentioned_ids(body: str) -> set[int]:
    return {int(m.group(2)) for m in MENTION_RE.finditer(body or "")}


def is_manager_or_admin(user) -> bool:
    return user.is_superuser or user.role in (ADMIN, MANAGER)


def can_change_comment(user, comment) -> bool:
    return comment.author_id == user.pk


def can_delete_comment(user, comment) -> bool:
    # Managers only reach comments on tasks they can see (their department), admins everything.
    return comment.author_id == user.pk or is_manager_or_admin(user)


def can_delete_attachment(user, attachment) -> bool:
    return attachment.uploaded_by_id == user.pk or is_manager_or_admin(user)


def can_edit_task(user) -> bool:
    return has_perm(user, "tasks", "edit")


def record(task, actor, kind: str, **data):
    return TaskActivity.objects.create(task=task, actor=actor if getattr(actor, "is_authenticated", True) else None, kind=kind, data=data)


def notify_comment(comment, actor):
    """Mentioned people get a mention notice; assignees and the creator get a new-comment notice (never the author)."""
    from apps.notifications.models import NotificationType
    from apps.notifications.services import notify

    task = comment.task
    params = {"actor": actor.full_name, "task": task.title, "task_id": task.pk}
    link = f"/tasks/{task.pk}#comment-{comment.pk}"
    mentioned = set(comment.mentions.exclude(pk=actor.pk))
    if mentioned:
        notify(list(mentioned), NotificationType.MENTION, link=link, actor=actor, message="task_mention", params=params)
    followers = {*task.assignees.filter(is_active=True), *([task.created_by] if task.created_by else [])}
    followers = {u for u in followers if u.pk != actor.pk and u not in mentioned}
    if followers:
        notify(list(followers), NotificationType.TASK_COMMENT, link=link, actor=actor, message="task_comment", params=params)
