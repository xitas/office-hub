"""Weeks, goals, progress, carrying over and the end-of-week reminder (used by the API, seed and tests)."""
from datetime import date, datetime, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.core.models import OrganizationSettings
from apps.core.office_time import office_now, office_tz
from apps.notifications.models import NotificationType
from apps.notifications.services import notify

from . import rules
from .models import GoalReminder, GoalUpdate, WeeklyGoal

LINK = "/planning"
REMIND_BEFORE_CLOSING = timedelta(hours=2)


class PlanningError(ValueError):
    """{field: message}"""

    def __init__(self, errors: dict):
        self.errors = errors
        super().__init__(next(iter(errors.values())))


# ================================================================ weeks


def week_start_of(day: date) -> date:
    """The first day of the office week holding `day` (Organization page: 1 Monday, 0 Sunday, 6 Saturday)."""
    first = OrganizationSettings.cached().week_start
    sunday_based = (day.weekday() + 1) % 7
    return day - timedelta(days=(sunday_based - first) % 7)


def last_working_day(week_start: date) -> date | None:
    """The week's last working day that isn't an office holiday (None if the whole week is off)."""
    from apps.leave.services import holidays_between

    working = set(OrganizationSettings.cached().working_days)
    days = [week_start + timedelta(days=i) for i in range(7)]
    holidays = holidays_between(days[0], days[-1])
    open_days = [d for d in days if d.weekday() in working and d not in holidays]
    return open_days[-1] if open_days else None


# ================================================================ goals


def check_owner(department_id, owner):
    if owner is not None and department_id is not None and owner.department_id != department_id:
        raise PlanningError({"owner": _("The owner has to be in the goal's department.")})
    if owner is not None and not owner.is_active:
        raise PlanningError({"owner": _("This person's account is not active.")})


def announce_owner(goal, actor):
    if goal.owner_id and goal.owner_id != actor.pk:
        pk, actor_pk = goal.pk, actor.pk
        transaction.on_commit(lambda: _tell_owner(pk, actor_pk))


def _tell_owner(pk, actor_pk):
    goal = WeeklyGoal.objects.select_related("owner").get(pk=pk)
    notify(goal.owner, NotificationType.PLANNING, link=f"{LINK}?week={goal.week_start}", actor=User.objects.get(pk=actor_pk),
           message="goal_assigned", params=_params(goal))


def record(user, goal, *, value=None, add=None, note="") -> GoalUpdate:
    """Set the progress to `value`, or add `add` to it (negative to correct). The goal row is locked."""
    if not rules.can_record(user, goal):
        raise PermissionError
    with transaction.atomic():
        goal = WeeklyGoal.objects.select_for_update().get(pk=goal.pk)
        before = goal.current
        after = value if value is not None else before + (add or 0)
        if after < 0:
            raise PlanningError({"value": _("Progress can't be below zero.")})
        if after > goal.target * 10:
            raise PlanningError({"value": _("That's far beyond the target. Check the number.")})
        goal.current = after
        was_done = before >= goal.target
        goal.completed_at = (goal.completed_at or timezone.now()) if goal.done else None
        goal.save(update_fields=["current", "completed_at", "updated_at"])
        update = GoalUpdate.objects.create(goal=goal, before=before, after=after, note=note.strip()[:300], by=user)
        if goal.done and not was_done:
            pk, actor_pk = goal.pk, user.pk
            transaction.on_commit(lambda: _tell_done(pk, actor_pk))
    return update


def _tell_done(pk, actor_pk):
    goal = WeeklyGoal.objects.select_related("owner", "created_by").get(pk=pk)
    people = set(User.objects.filter(is_active=True, role="manager", department_id=goal.department_id)) if goal.department_id else set()
    people |= {p for p in (goal.created_by, goal.owner) if p}
    notify(people, NotificationType.PLANNING, link=f"{LINK}?week={goal.week_start}", actor=User.objects.get(pk=actor_pk),
           message="goal_done", params=_params(goal))


def carry_over(user, week_start: date, department_id=None, *, all_departments=False) -> list[WeeklyGoal]:
    """Copy the week's unfinished goals (that this person plans) to the next week, with what's left of the target.
    A goal is copied once; the copies keep the owner, unit and description."""
    goals = WeeklyGoal.objects.filter(week_start=week_start)
    if not all_departments:
        goals = goals.filter(department_id=department_id)
    copied = set(WeeklyGoal.objects.filter(carried_from__in=goals).values_list("carried_from_id", flat=True))
    out = []
    with transaction.atomic():
        for g in goals.order_by("position", "id"):
            if g.done or g.pk in copied or not rules.can_manage(user, g):
                continue
            out.append(WeeklyGoal.objects.create(
                week_start=week_start + timedelta(days=7), department_id=g.department_id, title=g.title,
                description=g.description, owner=g.owner if g.owner and g.owner.is_active else None,
                target=g.target - g.current, unit=g.unit, position=g.position, carried_from=g, created_by=user,
            ))
    return out


# ================================================================ end-of-week reminder


def send_reminders(now=None) -> int:
    """On the week's last working day, from two hours before closing: owners of unfinished goals, once a week."""
    now = (now or office_now()).astimezone(office_tz())
    week = week_start_of(now.date())
    if last_working_day(week) != now.date():
        return 0
    closes = datetime.combine(now.date(), OrganizationSettings.cached().office_closes, tzinfo=office_tz())
    if now < closes - REMIND_BEFORE_CLOSING:
        return 0
    open_goals = WeeklyGoal.objects.filter(week_start=week, owner__isnull=False, owner__is_active=True).select_related("owner")
    by_owner: dict[int, list] = {}
    for g in open_goals:
        if not g.done:
            by_owner.setdefault(g.owner_id, []).append(g)
    sent = 0
    for goals in by_owner.values():
        owner = goals[0].owner
        try:
            with transaction.atomic():
                GoalReminder.objects.create(user=owner, week_start=week)
        except IntegrityError:
            continue
        notify(owner, NotificationType.PLANNING, link=f"{LINK}?week={week}", message="goal_reminder", params={
            "count": len(goals), "titles": [g.title for g in goals[:3]], "closes": closes.isoformat(),
        })
        sent += 1
    return sent


def _params(goal) -> dict:
    return {
        "title": goal.title, "current": goal.current, "target": goal.target, "unit": goal.unit,
        "week": goal.week_start.isoformat(), "owner": goal.owner.full_name if goal.owner else "",
    }
