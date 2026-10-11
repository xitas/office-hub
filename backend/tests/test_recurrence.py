"""Repeating tasks: rule dates (month ends, leap years, intervals), series behaviour and edits."""
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from unittest import mock

import pytest

from apps.tasks import schedule
from apps.tasks.models import ChecklistItem, Task, TaskAttachment, TaskComment, TaskSeries
from apps.tasks.recurrence import Rule

TASKS = "/api/v1/tasks/"


def dates(rule, n, after=None):
    out, d = [], (after or rule.start - timedelta(days=1))
    for _ in range(n):
        d = rule.next_after(d)
        if d is None:
            break
        out.append(d)
    return out


# ================================================================ rule dates (no database)


def test_daily_and_every_n_days():
    assert dates(Rule("daily", date(2026, 10, 30)), 4) == [date(2026, 10, 30), date(2026, 10, 31), date(2026, 11, 1), date(2026, 11, 2)]
    assert dates(Rule("daily", date(2026, 12, 30), interval=3), 3) == [date(2026, 12, 30), date(2027, 1, 2), date(2027, 1, 5)]


def test_weekly_chosen_days():
    # Monday and Thursday, starting Mon 5 Oct 2026.
    rule = Rule("weekly", date(2026, 10, 5), weekdays=[0, 3])
    assert dates(rule, 5) == [date(2026, 10, 5), date(2026, 10, 8), date(2026, 10, 12), date(2026, 10, 15), date(2026, 10, 19)]


def test_every_two_weeks():
    rule = Rule("weekly", date(2026, 10, 7), interval=2, weekdays=[2])  # every other Wednesday
    assert dates(rule, 3) == [date(2026, 10, 7), date(2026, 10, 21), date(2026, 11, 4)]


def test_weekly_defaults_to_the_start_day():
    assert Rule("weekly", date(2026, 10, 9)).weekdays == [4]  # Friday


@pytest.mark.parametrize("start,expected", [
    # The 31st falls back to the last day of shorter months.
    (date(2027, 1, 31), [date(2027, 1, 31), date(2027, 2, 28), date(2027, 3, 31), date(2027, 4, 30)]),
    # Leap year: the 29th/31st land on 29 February.
    (date(2028, 1, 31), [date(2028, 1, 31), date(2028, 2, 29), date(2028, 3, 31)]),
    (date(2028, 1, 29), [date(2028, 1, 29), date(2028, 2, 29), date(2028, 3, 29)]),
    # A 29th in a common year.
    (date(2027, 1, 29), [date(2027, 1, 29), date(2027, 2, 28), date(2027, 3, 29)]),
])
def test_monthly_day_of_month_at_month_ends(start, expected):
    assert dates(Rule("monthly", start), len(expected)) == expected


def test_monthly_from_leap_day():
    rule = Rule("monthly", date(2028, 2, 29), interval=12)  # yearly on 29 February
    assert dates(rule, 3) == [date(2028, 2, 29), date(2029, 2, 28), date(2030, 2, 28)]


def test_last_friday_of_the_month():
    rule = Rule("monthly", date(2026, 10, 30), monthly_mode="weekday", month_week=-1, month_weekday=4)
    assert dates(rule, 4) == [date(2026, 10, 30), date(2026, 11, 27), date(2026, 12, 25), date(2027, 1, 29)]


def test_second_tuesday_and_first_monday():
    second_tuesday = Rule("monthly", date(2026, 10, 13), monthly_mode="weekday", month_week=2, month_weekday=1)
    assert dates(second_tuesday, 3) == [date(2026, 10, 13), date(2026, 11, 10), date(2026, 12, 8)]
    first_monday = Rule("monthly", date(2026, 10, 5), monthly_mode="weekday")  # inferred from the start date
    assert (first_monday.month_week, first_monday.month_weekday) == (1, 0)
    assert dates(first_monday, 3) == [date(2026, 10, 5), date(2026, 11, 2), date(2026, 12, 7)]


def test_every_three_months():
    assert dates(Rule("monthly", date(2026, 11, 30), interval=3), 3) == [date(2026, 11, 30), date(2027, 2, 28), date(2027, 5, 30)]


def test_end_date_and_not_before():
    rule = Rule("daily", date(2026, 10, 1), end_date=date(2026, 10, 3))
    assert dates(rule, 10) == [date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)]
    weekly = Rule("weekly", date(2026, 10, 5), weekdays=[0])
    # Catch-up: from the last occurrence in early October, the next one on or after 1 December.
    assert weekly.next_after(date(2026, 10, 5), not_before=date(2026, 12, 1)) == date(2026, 12, 7)


# ================================================================ series (database)

pytestmark = pytest.mark.django_db


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {"admin": admin, "manager": manager, "staff": staff, "colleague": make_user("colleague@test.com")}


def at_utc(*args):
    return mock.patch("django.utils.timezone.now", return_value=datetime(*args, tzinfo=dt_timezone.utc))


def at_office(day, hour=10, minute=0):
    """Freeze "now" at a wall-clock time in Karachi (UTC+5)."""
    moment = datetime.combine(day, time(hour, minute)) - timedelta(hours=5)
    return at_utc(moment.year, moment.month, moment.day, moment.hour, moment.minute)


def create(client, **extra):
    body = {"title": "Weekly report", "due_date": "2026-10-12", "priority": "high",
            "recurrence": {"frequency": "weekly", "weekdays": [0]}, **extra}
    res = client.post(TASKS, body, format="json")
    assert res.status_code == 201, res.data
    return Task.objects.get(pk=res.data["id"])


def complete(client, task):
    res = client.patch(f"{TASKS}{task.pk}/", {"status": "done"}, format="json")
    assert res.status_code == 200, res.data


def test_create_repeating_task(client_for, people):
    c = client_for(people["staff"])
    with at_office(date(2026, 10, 10)):
        task = create(c)
        res = c.get(f"{TASKS}{task.pk}/").data
    assert res["repeat"]["frequency"] == "weekly" and res["repeat"]["weekdays"] == [0] and res["repeat"]["active"] is True
    assert task.series.start_date == date(2026, 10, 12)


def test_repeating_needs_a_due_date_and_valid_rule(client_for, people):
    c = client_for(people["staff"])
    res = c.post(TASKS, {"title": "x", "recurrence": {"frequency": "daily"}}, format="json")
    assert res.status_code == 400 and "recurrence" in res.data["errors"]
    res = c.post(TASKS, {"title": "x", "due_date": "2026-10-12", "recurrence": {"frequency": "weekly", "weekdays": []}}, format="json")
    assert res.status_code == 400
    res = c.post(TASKS, {"title": "x", "due_date": "2026-10-12", "recurrence": {"frequency": "daily", "end_date": "2026-10-01"}}, format="json")
    assert res.status_code == 400


def test_completing_creates_the_next_occurrence_with_a_fresh_copy(client_for, people):
    c = client_for(people["staff"])
    with at_office(date(2026, 10, 10)):
        task = create(c, assignees=[people["staff"].pk, people["colleague"].pk])
        ChecklistItem.objects.create(task=task, text="Collect numbers", done=True, position=1)
        schedule.update_template(task.series, task)  # the checklist joins the template
        TaskComment.objects.create(task=task, author=people["staff"], body="Done early")
        complete(c, task)
    nxt = Task.objects.exclude(pk=task.pk).get()
    assert nxt.due_date == date(2026, 10, 19) and nxt.status == "todo" and nxt.series_id == task.series_id
    assert (nxt.title, nxt.priority) == ("Weekly report", "high")
    assert set(nxt.assignees.all()) == {people["staff"], people["colleague"]}
    assert list(nxt.checklist.values_list("text", "done")) == [("Collect numbers", False)]
    assert not TaskComment.objects.filter(task=nxt).exists() and not TaskAttachment.objects.filter(task=nxt).exists()
    # Reopening and completing again doesn't make a second copy.
    c.patch(f"{TASKS}{task.pk}/", {"status": "todo"}, format="json")
    with at_office(date(2026, 10, 10)):
        complete(c, task)
    assert Task.objects.count() == 2


def test_completing_late_skips_missed_dates(client_for, people):
    c = client_for(people["staff"])
    with at_office(date(2026, 10, 10)):
        task = create(c)
    with at_office(date(2026, 11, 4)):  # three Mondays later
        complete(c, task)
    assert Task.objects.exclude(pk=task.pk).get().due_date == date(2026, 11, 9)


def test_count_and_end_date_stop_the_series(client_for, people):
    c = client_for(people["staff"])
    with at_office(date(2026, 10, 10)):
        task = create(c, recurrence={"frequency": "daily", "count": 2})
        complete(c, task)
        second = Task.objects.exclude(pk=task.pk).get()
        complete(c, second)
    assert Task.objects.count() == 2 and TaskSeries.objects.get().active is False
    with at_office(date(2026, 10, 10)):
        t2 = create(c, title="Until 13th", due_date="2026-10-12", recurrence={"frequency": "daily", "end_date": "2026-10-13"})
        complete(c, t2)
        complete(c, Task.objects.get(title="Until 13th", due_date=date(2026, 10, 13)))
    assert Task.objects.filter(title="Until 13th").count() == 2


def test_edit_this_occurrence_only(client_for, people):
    c = client_for(people["staff"])
    with at_office(date(2026, 10, 10)):
        task = create(c)
        c.patch(f"{TASKS}{task.pk}/", {"title": "Weekly report (holiday edition)", "scope": "this"}, format="json")
        complete(c, task)
    assert Task.objects.exclude(pk=task.pk).get().title == "Weekly report"


def test_edit_this_and_future(client_for, people):
    c = client_for(people["staff"])
    with at_office(date(2026, 10, 10)):
        task = create(c)
        complete(c, task)
        upcoming = Task.objects.exclude(pk=task.pk).get()
        res = c.patch(f"{TASKS}{task.pk}/", {"title": "Weekly sales report", "priority": "urgent", "scope": "future"}, format="json")
        assert res.status_code == 200
    upcoming.refresh_from_db()
    assert (upcoming.title, upcoming.priority) == ("Weekly sales report", "urgent")  # the open later occurrence
    with at_office(date(2026, 10, 17)):
        complete(c, upcoming)
    third = Task.objects.order_by("-due_date").first()
    assert (third.title, third.priority, third.due_date) == ("Weekly sales report", "urgent", date(2026, 10, 26))


def test_change_rule_from_this_occurrence(client_for, people):
    c = client_for(people["staff"])
    with at_office(date(2026, 10, 10)):
        task = create(c)
        res = c.patch(f"{TASKS}{task.pk}/", {"recurrence": {"frequency": "weekly", "weekdays": [0, 3]}, "scope": "future"}, format="json")
        assert res.data["repeat"]["weekdays"] == [0, 3]
        complete(c, task)
    assert Task.objects.exclude(pk=task.pk).get().due_date == date(2026, 10, 15)  # the Thursday


def test_stop_recurrence(client_for, people):
    c = client_for(people["staff"])
    with at_office(date(2026, 10, 10)):
        task = create(c)
        res = c.patch(f"{TASKS}{task.pk}/", {"recurrence": None}, format="json")
        assert res.data["repeat"]["active"] is False
        complete(c, task)
    assert Task.objects.count() == 1


def test_scheduled_generation_when_not_completed(client_for, people):
    c = client_for(people["staff"])
    with at_office(date(2026, 10, 10)):
        task = create(c)
    with at_office(date(2026, 10, 12, ), 18):
        assert schedule.generate_due_occurrences() == 0  # still due today
    with at_office(date(2026, 10, 13), 9):
        assert schedule.generate_due_occurrences() == 1
        assert schedule.generate_due_occurrences() == 0  # never twice
    assert Task.objects.exclude(pk=task.pk).get().due_date == date(2026, 10, 19)
    assert Task.objects.get(pk=task.pk).status == "todo"  # the missed one stays open (overdue)


def test_catch_up_after_downtime_creates_one_occurrence(client_for, people):
    c = client_for(people["staff"])
    with at_office(date(2026, 10, 10)):
        create(c, recurrence={"frequency": "daily"})
    with at_office(date(2026, 10, 30), 9):  # the scheduler was off for weeks
        assert schedule.generate_due_occurrences() == 1
    assert sorted(Task.objects.values_list("due_date", flat=True)) == [date(2026, 10, 12), date(2026, 10, 30)]


def test_new_day_starts_at_office_midnight(client_for, people):
    c = client_for(people["staff"])
    with at_office(date(2026, 10, 10)):
        create(c, due_date="2026-10-12", recurrence={"frequency": "daily"})
    # 18:59 UTC on the 12th is 23:59 in Karachi: the task is still due "today".
    with at_utc(2026, 10, 12, 18, 59):
        assert schedule.generate_due_occurrences() == 0
    # 19:01 UTC is 00:01 on the 13th in Karachi, while it's still the 12th in UTC.
    with at_utc(2026, 10, 12, 19, 1):
        assert schedule.generate_due_occurrences() == 1
    assert Task.objects.order_by("-due_date").first().due_date == date(2026, 10, 13)


def test_repeat_shows_on_list(client_for, people):
    c = client_for(people["staff"])
    with at_office(date(2026, 10, 10)):
        create(c, recurrence={"frequency": "monthly", "monthly_mode": "weekday", "month_week": -1, "month_weekday": 4})
    row = c.get(TASKS).data["results"][0]
    assert row["repeat"]["month_week"] == -1 and row["repeat"]["month_weekday"] == 4
