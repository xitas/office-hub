"""Board and calendar: status and due-date moves, Done window, and office-time-zone dates around midnight."""
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from unittest import mock

import pytest

from apps.core.models import AuditLog, OrganizationSettings
from apps.core.office_time import office_today
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db

TASKS = "/api/v1/tasks/"
BOARD = "/api/v1/tasks/board/"
CALENDAR = "/api/v1/tasks/calendar/"


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {
        "admin": admin, "manager": manager, "staff": staff,
        "colleague": make_user("colleague@test.com"),
        "outsider": make_user("ops.person@test.com", department="ops"),
    }


def make(title, creator, assignees=(), **extra):
    task = Task.objects.create(title=title, created_by=creator, **extra)
    task.assignees.set(assignees or [creator])
    return task


def at_utc(*args):
    """Freeze "now" at a UTC moment."""
    return mock.patch("django.utils.timezone.now", return_value=datetime(*args, tzinfo=dt_timezone.utc))


def column(res, status):
    return next(c for c in res.data["columns"] if c["status"] == status)


# ================================================================ board


def test_board_columns_counts_and_scoping(client_for, people):
    s = people["staff"]
    make("A", s)
    make("B", s, status="in_progress")
    make("C", s, status="review")
    make("Hidden", people["outsider"], status="in_progress")
    res = client_for(s).get(BOARD)
    assert [c["status"] for c in res.data["columns"]] == ["todo", "in_progress", "review", "done"]
    assert [c["count"] for c in res.data["columns"]] == [1, 1, 1, 0]
    assert [t["title"] for t in column(res, "in_progress")["cards"]] == ["B"]  # outsider's task not shown


def test_board_done_column_shows_last_14_days(client_for, people):
    s = people["staff"]
    recent = make("Done yesterday", s, status="done")
    old = make("Done last month", s, status="done")
    Task.objects.filter(pk=old.pk).update(completed_at=recent.completed_at - timedelta(days=30))
    res = client_for(s).get(BOARD)
    done = column(res, "done")
    assert [t["title"] for t in done["cards"]] == ["Done yesterday"]
    assert done["count"] == 1 and done["total"] == 2 and res.data["done_window_days"] == 14


def test_board_uses_list_filters_but_not_status(client_for, people):
    s = people["staff"]
    make("Urgent one", s, priority="urgent")
    make("Low one", s, priority="low", status="review")
    res = client_for(s).get(BOARD, {"priority": "urgent", "status": "review"})
    assert column(res, "todo")["count"] == 1 and column(res, "review")["count"] == 0
    res = client_for(s).get(BOARD, {"search": "low"})
    assert column(res, "review")["count"] == 1 and column(res, "todo")["count"] == 0


@pytest.mark.parametrize("who,owner,allowed", [
    ("staff", "staff", True),
    ("manager", "colleague", True),  # department task
    ("staff", "outsider", False),  # can't see it -> 404
    ("admin", "outsider", True),
])
def test_moving_a_card_is_a_status_change(client_for, people, who, owner, allowed):
    task = make("Move me", people[owner])
    res = client_for(people[who]).patch(f"{TASKS}{task.pk}/", {"status": "review"}, format="json")
    assert res.status_code == (200 if allowed else 404)
    task.refresh_from_db()
    assert (task.status == "review") is allowed
    log = AuditLog.objects.filter(action=AuditLog.Action.UPDATE, object_id=str(task.pk)).first()
    assert (log is not None and log.changes["status"] == ["todo", "review"] and log.actor == people[who]) is allowed


def test_moving_to_done_and_back(client_for, people):
    task = make("Finish", people["staff"])
    c = client_for(people["staff"])
    c.patch(f"{TASKS}{task.pk}/", {"status": "done"}, format="json")
    assert column(c.get(BOARD), "done")["count"] == 1
    c.patch(f"{TASKS}{task.pk}/", {"status": "in_progress"}, format="json")
    task.refresh_from_db()
    assert task.completed_at is None and column(c.get(BOARD), "done")["count"] == 0


# ================================================================ calendar


def test_calendar_range_and_undated(client_for, people):
    s = people["staff"]
    make("Oct 1", s, due_date=date(2026, 10, 1))
    make("Oct 31", s, due_date=date(2026, 10, 31), due_time=time(9, 30))
    make("Nov 1", s, due_date=date(2026, 11, 1))
    make("No date", s)
    make("Done, no date", s, status="done")
    make("Hidden", people["outsider"], due_date=date(2026, 10, 15))
    res = client_for(s).get(CALENDAR, {"start": "2026-10-01", "end": "2026-10-31"})
    assert [t["title"] for t in res.data["tasks"]] == ["Oct 1", "Oct 31"]  # both ends included
    assert [t["title"] for t in res.data["undated"]] == ["No date"] and res.data["undated_count"] == 1


def test_calendar_applies_filters(client_for, people):
    s = people["staff"]
    make("Mine", s, due_date=date(2026, 10, 5))
    make("Colleague's", people["colleague"], [people["colleague"]], due_date=date(2026, 10, 5))
    res = client_for(people["manager"]).get(CALENDAR, {"start": "2026-10-01", "end": "2026-10-31", "assigned_to": s.pk})
    assert [t["title"] for t in res.data["tasks"]] == ["Mine"]


@pytest.mark.parametrize("params", [
    {"start": "2026-10-01"},
    {"start": "bad", "end": "2026-10-31"},
    {"start": "2026-10-31", "end": "2026-10-01"},
    {"start": "2026-01-01", "end": "2026-12-31"},  # too long
])
def test_calendar_rejects_bad_ranges(client_for, people, params):
    assert client_for(people["staff"]).get(CALENDAR, params).status_code == 400


@pytest.mark.parametrize("who,owner,allowed", [
    ("staff", "staff", True),
    ("manager", "colleague", True),
    ("staff", "outsider", False),
])
def test_dragging_to_another_day_changes_the_due_date(client_for, people, who, owner, allowed):
    task = make("Reschedule", people[owner], due_date=date(2026, 10, 5), due_time=time(14, 0))
    res = client_for(people[who]).patch(f"{TASKS}{task.pk}/", {"due_date": "2026-10-08"}, format="json")
    assert res.status_code == (200 if allowed else 404)
    task.refresh_from_db()
    assert (task.due_date == date(2026, 10, 8)) is allowed
    assert task.due_time == time(14, 0)  # the time of day stays
    log = AuditLog.objects.filter(action=AuditLog.Action.UPDATE, object_id=str(task.pk)).first()
    assert (log is not None and log.changes == {"due_date": ["2026-10-05", "2026-10-08"]}) is allowed


def test_clearing_the_date_moves_it_to_no_date(client_for, people):
    task = make("Someday", people["staff"], due_date=date(2026, 10, 5), due_time=time(9, 0))
    res = client_for(people["staff"]).patch(f"{TASKS}{task.pk}/", {"due_date": None, "due_time": None}, format="json")
    assert res.status_code == 200
    undated = client_for(people["staff"]).get(CALENDAR, {"start": "2026-10-01", "end": "2026-10-31"}).data["undated"]
    assert [t["title"] for t in undated] == ["Someday"]


# ================================================================ office time zone around midnight


def test_today_flips_at_the_office_midnight_not_utc(client_for, people):
    s = people["staff"]
    make("Due Oct 10", s, due_date=date(2026, 10, 10))
    make("Due Oct 11", s, due_date=date(2026, 10, 11))
    c = client_for(s)
    # 18:59 UTC = 23:59 in Karachi (UTC+5): still Oct 10 at the office.
    with at_utc(2026, 10, 10, 18, 59):
        assert office_today() == date(2026, 10, 10)
        assert [t["title"] for t in c.get(TASKS, {"due": "today"}).data["results"]] == ["Due Oct 10"]
        assert c.get(TASKS, {"due": "overdue"}).data["count"] == 0
    # 19:01 UTC = 00:01 Oct 11 in Karachi, though it's still Oct 10 in UTC.
    with at_utc(2026, 10, 10, 19, 1):
        assert office_today() == date(2026, 10, 11)
        assert [t["title"] for t in c.get(TASKS, {"due": "today"}).data["results"]] == ["Due Oct 11"]
        overdue = c.get(TASKS, {"due": "overdue"}).data["results"]
        assert [t["title"] for t in overdue] == ["Due Oct 10"] and overdue[0]["is_overdue"] is True
        assert c.get(CALENDAR, {"start": "2026-10-01", "end": "2026-10-31"}).data["today"] == date(2026, 10, 11)


def test_due_time_is_office_wall_clock(client_for, people):
    task = make("Call at 10", people["staff"], due_date=date(2026, 10, 10), due_time=time(10, 0))
    with at_utc(2026, 10, 10, 4, 59):  # 09:59 in Karachi
        task.refresh_from_db()
        assert task.is_overdue is False
    with at_utc(2026, 10, 10, 5, 1):  # 10:01 in Karachi
        assert task.is_overdue is True
        assert client_for(people["staff"]).get(TASKS, {"overdue": "true"}).data["count"] == 1


def test_organization_time_zone_setting_is_used(client_for, people):
    org = OrganizationSettings.get_solo()
    org.timezone = "America/New_York"  # UTC-4 in October
    org.save()
    make("Due Oct 10", people["staff"], due_date=date(2026, 10, 10))
    # 02:00 UTC Oct 11 is still 22:00 Oct 10 in New York.
    with at_utc(2026, 10, 11, 2, 0):
        assert office_today() == date(2026, 10, 10)
        res = client_for(people["staff"]).get(TASKS, {"due": "today"})
        assert [t["title"] for t in res.data["results"]] == ["Due Oct 10"]


def test_unknown_time_zone_falls_back_to_server_default():
    org = OrganizationSettings.get_solo()
    OrganizationSettings.objects.filter(pk=org.pk).update(timezone="Mars/Olympus")
    from django.core.cache import cache

    cache.clear()
    assert office_today()  # no crash; uses settings.TIME_ZONE
