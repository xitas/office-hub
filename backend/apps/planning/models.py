"""Weekly planning: each team's goals for a week, with progress.

- A goal belongs to a week (the office week, starting on the Organization page's first day) and to a
  department, or to the whole office (no department). It has a target number and a unit
  ("5 quotations", "100 %"), and the current progress towards it. An owner is optional.
- Managers set their department's goals; admins set anyone's, and office-wide ones. The goal's owner,
  the department's managers and admins record progress; each change is kept (GoalUpdate).
- Unfinished goals can be copied to the next week with what's left of the target.
- On the last working day of the week, owners of unfinished goals are reminded once (GoalReminder).
"""
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class WeeklyGoal(models.Model):
    week_start = models.DateField(db_index=True)
    department = models.ForeignKey(
        "accounts.Department", null=True, blank=True, on_delete=models.CASCADE, related_name="weekly_goals",
        help_text="Empty: the whole office",
    )
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="weekly_goals")
    target = models.PositiveIntegerField(default=1)
    unit = models.CharField(max_length=40, blank=True, help_text="quotations, visits, %…")
    current = models.PositiveIntegerField(default=0)
    position = models.PositiveSmallIntegerField(default=0)
    carried_from = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["week_start", "position", "id"]
        indexes = [models.Index(fields=["week_start", "department"], name="goal_week_dept_idx")]
        constraints = [models.CheckConstraint(condition=models.Q(target__gt=0), name="goal_target_positive")]
        verbose_name = _("weekly goal")
        verbose_name_plural = _("weekly goals")

    def __str__(self):
        return self.title

    @property
    def done(self) -> bool:
        return self.current >= self.target


class GoalUpdate(models.Model):
    """One change to a goal's progress."""

    goal = models.ForeignKey(WeeklyGoal, on_delete=models.CASCADE, related_name="updates")
    before = models.PositiveIntegerField()
    after = models.PositiveIntegerField()
    note = models.CharField(max_length=300, blank=True)
    by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = _("goal update")
        verbose_name_plural = _("goal updates")


class GoalReminder(models.Model):
    """The end-of-week reminder a person got for a week (at most one)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    week_start = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "week_start"], name="one_goal_reminder_per_week")]
