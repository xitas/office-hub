"""Repeating tasks, reminders and the morning digest (run by Celery Beat; see tasks.py).

Nothing here is sent twice: every reminder is recorded in ReminderLog (unique per task, person,
kind and due moment) and every digest in DigestLog (one per person per office day) *before* it goes
out, so a retried or overlapping run finds the record and skips.

After the worker or Beat has been down, the next run catches up without flooding:
- "due soon" only for tasks that are not yet due (late reminders would be noise);
- "overdue" only for tasks that became overdue in the last OVERDUE_CATCH_UP (older ones are in the digest);
- the digest only for today, and only until DIGEST_LAST_HOUR (no stale "good morning" in the evening);
- repeating tasks jump to their next date from today instead of creating every missed occurrence.
"""
import logging
from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from apps.accounts.models import User
from apps.core.email import queue_email
from apps.core.office_time import office_datetime, office_now, office_tz

from .models import ChecklistItem, DigestLog, ReminderLog, Task, TaskActivity, TaskSeries, overdue_q

logger = logging.getLogger(__name__)

LEADS = {"1h": timedelta(hours=1), "1d": timedelta(days=1)}
OVERDUE_CATCH_UP = timedelta(days=2)
DIGEST_HOUR = 9
DIGEST_LAST_HOUR = 13
FOLLOW_UP_LOOKBACK = timedelta(days=7)


# ================================================================ repeating tasks


RULE_FIELDS = ("frequency", "interval", "weekdays", "monthly_mode", "month_day", "month_week", "month_weekday", "end_date", "count")


def snapshot_template(task) -> dict:
    return {
        "title": task.title,
        "description": task.description,
        "priority": task.priority,
        "assignee_ids": list(task.assignees.values_list("pk", flat=True)),
        "due_time": task.due_time,
        "contact": task.contact,
        "company": task.company,
        "checklist": list(task.checklist.values_list("text", flat=True)),
    }


def start_series(task, rule: dict, user) -> TaskSeries:
    """Make `task` the first occurrence of a new series."""
    series = TaskSeries.objects.create(start_date=task.due_date, created_by=user, **rule, **snapshot_template(task))
    task.series = series
    task.save(update_fields=["series"])
    return series


def update_rule(series, task, rule: dict):
    """New rule from this occurrence on (its due date becomes the rule's anchor)."""
    for name in RULE_FIELDS:
        setattr(series, name, rule.get(name, getattr(series, name)))
    series.start_date = task.due_date
    series.active = True
    series.save()


def update_template(series, task):
    for name, value in snapshot_template(task).items():
        setattr(series, name, value)
    series.save()


def stop_series(series):
    series.active = False
    series.save(update_fields=["active"])


def latest_occurrence(series):
    return series.occurrences.exclude(due_date__isnull=True).order_by("-due_date", "-id").first()


@transaction.atomic
def spawn_next(series, actor=None):
    """Create the occurrence after the series' latest one. Returns it, or None if the series has ended."""
    series = TaskSeries.objects.select_for_update().get(pk=series.pk)
    if not series.active:
        return None
    if series.count and series.occurrences_created >= series.count:
        stop_series(series)
        return None
    latest = latest_occurrence(series)
    after = latest.due_date if latest else series.start_date - timedelta(days=1)
    rule = series.rule()
    today = office_now().date()
    # Missed dates are skipped: the next occurrence is never in the past.
    nxt = rule.next_after(after, not_before=today)
    if nxt is None:
        stop_series(series)
        return None
    task = Task.objects.create(
        title=series.title, description=series.description, priority=series.priority, due_date=nxt,
        due_time=series.due_time, contact=series.contact, company=series.company, series=series,
        created_by=series.created_by, updated_by=series.created_by,
    )
    task.assignees.set(User.objects.filter(pk__in=series.assignee_ids, is_active=True) or [series.created_by])
    ChecklistItem.objects.bulk_create(
        [ChecklistItem(task=task, text=text, position=i, created_by=series.created_by) for i, text in enumerate(series.checklist, 1)]
    )
    TaskActivity.objects.create(task=task, actor=actor, kind="created", data={"recurring": True})
    series.occurrences_created += 1
    series.save(update_fields=["occurrences_created"])
    return task


def on_completed(task, actor=None):
    """When an occurrence is done, create the next one, unless a later one already exists."""
    series = task.series
    if not series or not series.active or task.due_date is None:
        return None
    if series.occurrences.filter(due_date__gt=task.due_date).exists():
        return None
    return spawn_next(series, actor)


def generate_due_occurrences(now=None) -> int:
    """Scheduled: series whose latest occurrence is past due (still open) get their next one."""
    now = now or timezone.now()
    today = now.astimezone(office_tz()).date()
    created = 0
    latest = TaskSeries.objects.filter(active=True).annotate(last_due=Max("occurrences__due_date"))
    for series in latest.filter(last_due__lt=today):
        try:
            if spawn_next(series):
                created += 1
        except Exception:  # one broken series must not stop the others
            logger.exception("Could not create the next occurrence of series %s", series.pk)
    return created


# ================================================================ notifications


def notify_assigned(task, users, actor):
    """'Assigned to you' for people newly put on a task (never for assigning yourself)."""
    from apps.notifications.models import NotificationType
    from apps.notifications.services import notify

    people = [u for u in users if actor is None or u.pk != actor.pk]
    if people:
        notify(
            people, NotificationType.TASK_ASSIGNED, link=f"/tasks/{task.pk}", actor=actor, message="task_assigned",
            params={"actor": actor.full_name if actor else "", "task": task.title, "task_id": task.pk},
        )


def _record(task, user, kind, due_at) -> bool:
    """Claim a reminder; False if it was already sent (by this or an overlapping run)."""
    try:
        with transaction.atomic():
            ReminderLog.objects.create(task=task, user=user, kind=kind, due_key=due_at.isoformat())
        return True
    except IntegrityError:
        return False


def send_due_soon(now=None) -> int:
    from apps.notifications.models import NotificationType
    from apps.notifications.services import notify

    now = now or timezone.now()
    today = now.astimezone(office_tz()).date()
    sent = 0
    tasks = (
        Task.objects.exclude(status=Task.Status.DONE)
        .filter(due_date__gte=today, due_date__lte=today + timedelta(days=2))
        .prefetch_related("assignees")
    )
    for task in tasks:
        due_at = task.due_at
        if due_at <= now:
            continue  # too late for "due soon"; the overdue reminder takes over
        for user in task.assignees.all():
            lead = LEADS.get(user.task_reminder_lead)
            if not user.is_active or lead is None or now < due_at - lead:
                continue
            if _record(task, user, ReminderLog.Kind.DUE_SOON, due_at):
                notify(
                    user, NotificationType.TASK_DEADLINE, link=f"/tasks/{task.pk}", message="task_due_soon",
                    params={"task": task.title, "task_id": task.pk, "due": due_at.isoformat(), "has_time": task.due_time is not None},
                )
                sent += 1
    return sent


def send_overdue(now=None) -> int:
    from apps.notifications.models import NotificationType
    from apps.notifications.services import notify

    now = now or timezone.now()
    today = now.astimezone(office_tz()).date()
    sent = 0
    earliest = (now - OVERDUE_CATCH_UP).astimezone(office_tz()).date()
    tasks = (
        Task.objects.exclude(status=Task.Status.DONE)
        .filter(due_date__gte=earliest, due_date__lte=today)
        .prefetch_related("assignees")
    )
    for task in tasks:
        due_at = task.due_at
        # Only once it really is overdue, and only if that happened recently (no flood after downtime).
        if not (now - OVERDUE_CATCH_UP <= due_at < now):
            continue
        for user in task.assignees.all():
            if user.is_active and _record(task, user, ReminderLog.Kind.OVERDUE, due_at):
                notify(
                    user, NotificationType.TASK_OVERDUE, link=f"/tasks/{task.pk}", message="task_overdue",
                    params={"task": task.title, "task_id": task.pk},
                )
                sent += 1
    return sent


# ================================================================ morning digest


def digest_for(user, today, now=None):
    """(due today, overdue, follow-ups) for one person on an office date.

    A task due earlier today whose time has already passed counts as overdue, not "due today".
    """
    from apps.timeline.models import TimelineEntry

    late = overdue_q(now)
    mine = Task.objects.filter(assignees=user).exclude(status=Task.Status.DONE)
    due_today = list(mine.filter(due_date=today).exclude(late).order_by("due_time", "title"))
    overdue = list(mine.filter(late).order_by("due_date", "due_time", "title")[:20])
    follow_ups = list(
        TimelineEntry.objects.filter(
            created_by=user, follow_up_on__lte=today, follow_up_on__gte=today - FOLLOW_UP_LOOKBACK, follow_up_tasks__isnull=True
        )
        .select_related("contact", "company")
        .order_by("follow_up_on")[:20]
    )
    return due_today, overdue, follow_ups


def render_digest(user, today, due_today, overdue, follow_ups) -> tuple[str, str]:
    base = settings.FRONTEND_URL.rstrip("/")
    with translation.override(user.language or settings.LANGUAGE_CODE):
        lines = [_("Good morning, %(name)s. Here is your day.") % {"name": user.full_name.split(" ")[0]}, ""]
        if due_today:
            lines.append(_("Due today (%(count)s):") % {"count": len(due_today)})
            for t in due_today:
                at = f" {t.due_time:%H:%M}" if t.due_time else ""
                lines.append(f"  • {t.title}{at} — {base}/tasks/{t.pk}")
            lines.append("")
        if overdue:
            lines.append(_("Overdue (%(count)s):") % {"count": len(overdue)})
            for t in overdue:
                at = f" {t.due_time:%H:%M}" if t.due_time and t.due_date == today else ""
                lines.append(f"  • {t.title} ({t.due_date:%d/%m/%Y}{at}) — {base}/tasks/{t.pk}")
            lines.append("")
        if follow_ups:
            lines.append(_("Client follow-ups (%(count)s):") % {"count": len(follow_ups)})
            for e in follow_ups:
                who = e.contact.full_name if e.contact else e.company.name
                path = f"/contacts/{e.contact_id}" if e.contact_id else f"/companies/{e.company_id}"
                summary = (e.summary or "").strip().splitlines()[0][:80] if e.summary else ""
                lines.append(f"  • {who}{': ' + summary if summary else ''} ({e.follow_up_on:%d/%m/%Y}) — {base}{path}")
            lines.append("")
        lines.append(_("You get this email because the morning digest is on in your notification settings."))
        parts = []
        if due_today:
            parts.append(ngettext("%(n)s task due today", "%(n)s tasks due today", len(due_today)) % {"n": len(due_today)})
        if overdue:
            parts.append(ngettext("%(n)s overdue", "%(n)s overdue", len(overdue)) % {"n": len(overdue)})
        if follow_ups:
            parts.append(ngettext("%(n)s client follow-up", "%(n)s client follow-ups", len(follow_ups)) % {"n": len(follow_ups)})
        subject = _("Your day: %(summary)s") % {"summary": _(", ").join(parts)}
        return subject, "\n".join(lines)


def send_digests(now=None) -> int:
    """Scheduled every few minutes; each person gets at most one digest per office day, from 9:00."""
    from apps.notifications.services import get_preferences

    now = now or timezone.now()
    local = now.astimezone(office_tz())
    if not (DIGEST_HOUR <= local.hour < DIGEST_LAST_HOUR):
        return 0
    today = local.date()
    done = set(DigestLog.objects.filter(date=today).values_list("user_id", flat=True))
    sent = 0
    for user in User.objects.filter(is_active=True).exclude(pk__in=done).exclude(email=""):
        if not get_preferences(user).get("daily_digest", {}).get("email"):
            continue
        due_today, overdue, follow_ups = digest_for(user, today, now)
        has_news = bool(due_today or overdue or follow_ups)
        try:
            with transaction.atomic():
                DigestLog.objects.create(user=user, date=today, sent=has_news)
        except IntegrityError:
            continue  # another run got there first
        if has_news:
            subject, body = render_digest(user, today, due_today, overdue, follow_ups)
            queue_email(subject, body, [user.email])
            sent += 1
    return sent


def office_moment(day, hour, minute=0) -> datetime:
    """Helper for tests and the scheduler: a wall-clock time at the office."""
    return office_datetime(day, time(hour, minute))
