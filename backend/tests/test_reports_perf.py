"""Report performance with a realistic dataset: a year of tasks for 50 people (about 13,000 tasks, some shared by
two people). Skipped unless REPORTS_PERF=1; run it on PostgreSQL:

    REPORTS_PERF=1 TEST_DATABASE_URL=... pytest tests/test_reports_perf.py -s

Prints each report's time and query count for an admin (everyone) and a manager (one department), including the
PDF and Excel exports.
"""
import os
import random
import time
from datetime import datetime, timedelta
from datetime import time as dtime

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import Department, User
from apps.core.office_time import office_today, office_tz
from apps.tasks.models import Task

pytestmark = [pytest.mark.django_db, pytest.mark.skipif(os.environ.get("REPORTS_PERF") != "1", reason="set REPORTS_PERF=1")]

PEOPLE, WEEKS, PER_WEEK = 50, 52, 5


def build():
    rnd = random.Random(7)
    depts = [Department.objects.create(name=n) for n in ("Perf Sales", "Perf Operations", "Perf Accounts")]
    users = [User.objects.create_user(email=f"perf{i}@t.com", password="x", full_name=f"Person {i:02d}",
                                      role="manager" if i < 3 else "staff", department=depts[i % 3]) for i in range(PEOPLE)]
    admin = User.objects.create_user(email="perf.admin@t.com", password="x", full_name="Perf Admin", role="admin")
    today, tz = office_today(), office_tz()
    tasks, links = [], []
    for u in users:
        for w in range(WEEKS):
            for k in range(PER_WEEK):
                due = today - timedelta(days=365) + timedelta(days=w * 7 + rnd.randint(0, 6) + 14)
                done = due < today and rnd.random() < 0.8
                finished = datetime.combine(due + timedelta(days=rnd.choice([-2, -1, 0, 0, 0, 1, 3])), dtime(rnd.randint(8, 19)), tzinfo=tz) if done else None
                tasks.append(Task(title=f"Task {u.pk}-{w}-{k}", due_date=due, status="done" if done else rnd.choice(["todo", "in_progress"]),
                                  completed_at=finished, priority=rnd.choice(["low", "medium", "high", "urgent"]), created_by=u))
    tasks = Task.objects.bulk_create(tasks, batch_size=2000)
    for t in tasks:
        owner = t.created_by_id
        links.append(Task.assignees.through(task_id=t.pk, user_id=owner))
        if rnd.random() < 0.15:
            other = rnd.choice(users).pk
            if other != owner:
                links.append(Task.assignees.through(task_id=t.pk, user_id=other))
    Task.assignees.through.objects.bulk_create(links, batch_size=5000)
    return admin, users[0], len(tasks), len(links)


def test_reports_with_a_year_of_data(client_for):
    admin, manager, n_tasks, n_links = build()
    today = office_today()
    year = {"from": (today - timedelta(days=365)).isoformat(), "to": today.isoformat()}
    month = {"from": today.replace(day=1).isoformat(), "to": today.isoformat()}
    urls = {
        "completion, a year": ("/api/v1/reports/task-completion/", year),
        "completion, this month": ("/api/v1/reports/task-completion/", month),
        "overdue": ("/api/v1/reports/overdue-tasks/", {}),
        "completion PDF, a year": ("/api/v1/reports/task-completion/export/", {**year, "file": "pdf"}),
        "completion Excel, a year": ("/api/v1/reports/task-completion/export/", {**year, "file": "xlsx"}),
        "overdue PDF": ("/api/v1/reports/overdue-tasks/export/", {"file": "pdf"}),
        "overdue Excel": ("/api/v1/reports/overdue-tasks/export/", {"file": "xlsx"}),
    }
    print(f"\n{n_tasks} tasks, {n_links} assignments, {PEOPLE} people ({connection.vendor})")
    for who, user, lang in (("admin", admin, "en"), ("manager", manager, "en"), ("manager", manager, "ur")):
        user.language = lang
        user.save(update_fields=["language"])
        who = f"{who} ({lang})"
        client = client_for(user)
        client.get(urls["overdue"][0])  # warm up
        for name, (url, params) in urls.items():
            with CaptureQueriesContext(connection) as ctx:
                start = time.perf_counter()
                res = client.get(url, params, HTTP_ACCEPT_LANGUAGE=lang)
                took = time.perf_counter() - start
            assert res.status_code == 200, (name, res.status_code)
            size = f", {len(res.content) // 1024} KB" if "export" in url else ""
            print(f"  {who:<13} {name:<26} {took * 1000:7.0f} ms  {len(ctx):2d} queries{size}")
            assert took < 5, f"{name} took {took:.1f}s"


def build_clients(users):
    """A year of client work for the same 50 people: about 3 new leads a week each (moving through the pipeline) and
    about 8 interactions a week each (calls, meetings, emails, WhatsApp, visit reports), plus some notes."""
    from apps.contacts.models import Contact, ContactStatusChange
    from apps.timeline.models import TimelineEntry

    rnd = random.Random(11)
    tz, today = office_tz(), office_today()
    created_at = Contact._meta.get_field("created_at")
    created_at.auto_now_add = False  # spread the leads over the year
    try:
        leads = []
        for u in users:
            for w in range(WEEKS):
                for k in range(3):
                    day = today - timedelta(days=364) + timedelta(days=w * 7 + rnd.randint(0, 6))
                    leads.append(Contact(first_name=f"Lead {u.pk}-{w}-{k}", assigned_to=u, created_at=datetime.combine(day, dtime(10), tzinfo=tz),
                                         updated_at=datetime.combine(day, dtime(10), tzinfo=tz)))
        leads = Contact.objects.bulk_create(leads, batch_size=2000)
    finally:
        created_at.auto_now_add = True
    changes, statuses = [], []
    for c in leads:
        path = rnd.choice([["new"], ["new", "contacted"], ["new", "contacted", "in_discussion"], ["new", "contacted", "in_discussion", "won"],
                           ["new", "contacted", "lost"], ["new", "in_discussion", "won"]])
        when = c.created_at
        previous = ""
        for status in path:
            changes.append(ContactStatusChange(contact_id=c.pk, from_status=previous, to_status=status, changed_at=when, changed_by_id=c.assigned_to_id))
            previous, when = status, when + timedelta(days=rnd.randint(1, 12))
        statuses.append((c.pk, path[-1]))
    ContactStatusChange.objects.bulk_create(changes, batch_size=5000)
    for status in ("contacted", "in_discussion", "won", "lost"):
        Contact.objects.filter(pk__in=[pk for pk, s in statuses if s == status]).update(status=status)
    by_owner = {}
    for c in leads:
        by_owner.setdefault(c.assigned_to_id, []).append(c.pk)
    entries = []
    for u in users:
        mine = by_owner[u.pk]
        for w in range(WEEKS):
            for k in range(9):
                day = today - timedelta(days=364) + timedelta(days=w * 7 + rnd.randint(0, 6))
                kind = rnd.choice(["call", "call", "meeting", "email", "whatsapp", "visit", "note"])
                entries.append(TimelineEntry(kind=kind, contact_id=rnd.choice(mine), summary="s", created_by=u,
                                             occurred_at=datetime.combine(day, dtime(rnd.randint(8, 19)), tzinfo=tz),
                                             details={"direction": "out", "outcome": "connected"} if kind == "call" else {}))
    TimelineEntry.objects.bulk_create(entries, batch_size=5000)
    return len(leads), len(changes), len(entries)


def test_client_reports_with_a_year_of_data(client_for):
    admin, manager, _n, _m = build()
    users = list(User.objects.filter(email__startswith="perf", role__in=["manager", "staff"]).order_by("pk"))
    n_leads, n_changes, n_entries = build_clients(users)
    today = office_today()
    year = {"from": (today - timedelta(days=364)).isoformat(), "to": today.isoformat()}
    urls = {
        "interactions by week": ("/api/v1/reports/client-interactions/", year),
        "interactions by month": ("/api/v1/reports/client-interactions/", {**year, "by": "month"}),
        "pipeline": ("/api/v1/reports/lead-pipeline/", year),
        "interactions PDF (weeks)": ("/api/v1/reports/client-interactions/export/", {**year, "file": "pdf"}),
        "interactions Excel": ("/api/v1/reports/client-interactions/export/", {**year, "file": "xlsx"}),
        "pipeline PDF": ("/api/v1/reports/lead-pipeline/export/", {**year, "file": "pdf"}),
        "pipeline Excel": ("/api/v1/reports/lead-pipeline/export/", {**year, "file": "xlsx"}),
    }
    print(f"\n{n_leads} leads, {n_changes} status changes, {n_entries} timeline entries, {PEOPLE} people ({connection.vendor})")
    for who, user, lang in (("admin", admin, "en"), ("manager", manager, "en"), ("manager", manager, "ur")):
        who = f"{who} ({lang})"
        client = client_for(user)
        client.get(urls["pipeline"][0], urls["pipeline"][1])  # warm up
        for name, (url, params) in urls.items():
            with CaptureQueriesContext(connection) as ctx:
                start = time.perf_counter()
                res = client.get(url, params, HTTP_ACCEPT_LANGUAGE=lang)
                took = time.perf_counter() - start
            assert res.status_code == 200, (name, res.status_code)
            size = f", {len(res.content) // 1024} KB" if "export" in url else ""
            print(f"  {who:<13} {name:<26} {took * 1000:7.0f} ms  {len(ctx):2d} queries{size}")
            assert took < 5, f"{name} took {took:.1f}s"


def build_field(users):
    """A year of field work for the same 50 people: about 3 visits a week each (most done, with the person's
    check-in and usually a report) and about 2 errands a week each in every state."""
    from apps.errands.models import Errand
    from apps.visits.models import Visit, VisitCheck, VisitReport

    rnd = random.Random(13)
    tz, today = office_tz(), office_today()
    visits, errands = [], []
    for u in users:
        for w in range(WEEKS):
            for k in range(3):
                day = today - timedelta(days=364) + timedelta(days=w * 7 + rnd.randint(0, 6))
                start = datetime.combine(day, dtime(rnd.randint(9, 16)), tzinfo=tz)
                past = day < today
                status = rnd.choice(["done"] * 7 + ["cancelled", "planned"]) if past else "planned"
                visits.append(Visit(title=f"V {u.pk}-{w}-{k}", place_name="Site", purpose=rnd.choice(["meeting", "delivery", "site", "collection", "support", "other"]),
                                    assigned_to=u, status=status, start=start, end=start + timedelta(hours=1), created_by=u))
            for k in range(2):
                day = today - timedelta(days=364) + timedelta(days=w * 7 + rnd.randint(0, 6))
                due = datetime.combine(day, dtime(rnd.randint(9, 17)), tzinfo=tz)
                past = day < today
                status = rnd.choice(["done"] * 6 + ["failed", "cancelled", "assigned"]) if past else rnd.choice(["assigned", "open"])
                errands.append(Errand(title=f"E {u.pk}-{w}-{k}", kind=rnd.choice(["courier", "pickup", "delivery", "bank", "other"]), place_name="Bank",
                                      assigned_to=None if status == "open" else u, requested_by=u, department_id=u.department_id, status=status,
                                      due_at=due, finished_at=due + timedelta(hours=rnd.randint(-3, 4)) if status in ("done", "failed") else None))
    visits = Visit.objects.bulk_create(visits, batch_size=2000)
    Errand.objects.bulk_create(errands, batch_size=2000)
    checks = [VisitCheck(visit_id=v.pk, user_id=v.assigned_to_id, checked_in_at=v.start, in_location="declined") for v in visits
              if v.status == "done" and rnd.random() < 0.85]
    VisitCheck.objects.bulk_create(checks, batch_size=5000)
    reports = [VisitReport(visit_id=v.pk, outcome=rnd.choice(["good", "follow_up", "no_result", "not_met"]), written_by_id=v.assigned_to_id)
               for v in visits if v.status == "done" and rnd.random() < 0.7]
    VisitReport.objects.bulk_create(reports, batch_size=5000)
    return len(visits), len(checks), len(reports), len(errands)


def test_field_reports_with_a_year_of_data(client_for):
    admin, manager, _n, _m = build()
    users = list(User.objects.filter(email__startswith="perf", role__in=["manager", "staff"]).order_by("pk"))
    n_visits, n_checks, n_reports, n_errands = build_field(users)
    today = office_today()
    year = {"from": (today - timedelta(days=364)).isoformat(), "to": today.isoformat()}
    month = {"from": today.replace(day=1).isoformat(), "to": today.isoformat()}
    urls = {
        "field visits, a year": ("/api/v1/reports/field-visits/", year),
        "field visits, this month": ("/api/v1/reports/field-visits/", month),
        "errands, a year": ("/api/v1/reports/errands/", year),
        "field visits PDF": ("/api/v1/reports/field-visits/export/", {**year, "file": "pdf"}),
        "field visits Excel": ("/api/v1/reports/field-visits/export/", {**year, "file": "xlsx"}),
        "errands PDF": ("/api/v1/reports/errands/export/", {**year, "file": "pdf"}),
        "errands Excel": ("/api/v1/reports/errands/export/", {**year, "file": "xlsx"}),
    }
    print(f"\n{n_visits} visits, {n_checks} check-ins, {n_reports} reports, {n_errands} errands, {PEOPLE} people ({connection.vendor})")
    for who, user, lang in (("admin", admin, "en"), ("manager", manager, "en"), ("manager", manager, "ur")):
        who = f"{who} ({lang})"
        client = client_for(user)
        client.get(urls["errands, a year"][0], year)  # warm up
        for name, (url, params) in urls.items():
            with CaptureQueriesContext(connection) as ctx:
                start = time.perf_counter()
                res = client.get(url, params, HTTP_ACCEPT_LANGUAGE=lang)
                took = time.perf_counter() - start
            assert res.status_code == 200, (name, res.status_code)
            size = f", {len(res.content) // 1024} KB" if "export" in url else ""
            print(f"  {who:<13} {name:<26} {took * 1000:7.0f} ms  {len(ctx):2d} queries{size}")
            assert took < 5, f"{name} took {took:.1f}s"


def build_attendance(users, admin):
    """A year of attendance for the same 50 people: a check-in on most working days (office, some remote and field
    visits, a few late), about a dozen leave requests each (some half days, some waiting), office holidays and
    stored balances."""
    from decimal import Decimal

    from apps.attendance.models import Attendance
    from apps.events.models import Event
    from apps.leave.models import LeaveBalance, LeaveRequest, LeaveType
    from apps.reports.scope import day_bounds

    rnd = random.Random(17)
    tz, today = office_tz(), office_today()
    first = today - timedelta(days=364)
    User.objects.filter(pk__in=[u.pk for u in users]).update(date_joined=datetime.combine(first - timedelta(days=30), dtime(9), tzinfo=tz))
    types = [LeaveType.objects.create(name=n, days_per_year=d, position=i)
             for i, (n, d) in enumerate((("Perf annual", Decimal("20")), ("Perf sick", Decimal("10")), ("Perf casual", Decimal("8")), ("Perf unpaid", None)))]
    holidays = {first + timedelta(days=d) for d in (40, 41, 120, 200, 290)}
    for h in holidays:
        start, end = day_bounds(h, h)
        Event.objects.create(kind="holiday", title="Perf holiday", all_day=True, start=start, end=end, organizer=admin)
    records, requests, balances = [], [], []
    for u in users:
        off: set = set()
        for _k in range(12):
            start = first + timedelta(days=rnd.randint(0, 360))
            if start.weekday() >= 5 or start in off:
                continue
            half = rnd.random() < 0.25
            end = start if half else min(start + timedelta(days=rnd.randint(0, 3)), start.replace(month=12, day=31))
            days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
            if off & set(days):
                continue
            off |= set(days)
            requests.append(LeaveRequest(user=u, leave_type=rnd.choice(types), start_date=start, end_date=end, half_day="morning" if half else "",
                                         days=Decimal("0.5") if half else sum(1 for d in days if d.weekday() < 5),
                                         status=rnd.choice(["approved"] * 5 + ["pending", "rejected"])))
        day = first
        while day <= today:
            if day.weekday() < 5 and day not in holidays and day not in off and rnd.random() < 0.9:
                mode = rnd.choice(["office"] * 8 + ["remote", "field"])
                moment = datetime.combine(day, dtime(8, 30), tzinfo=tz) + timedelta(minutes=rnd.randint(0, 75))
                records.append(Attendance(user=u, date=day, mode=mode, check_in=moment,
                                          check_out=moment + timedelta(hours=8) if day < today else None))
            day += timedelta(days=1)
        for t in types[:3]:
            for year in {first.year, today.year}:
                balances.append(LeaveBalance(user=u, leave_type=t, year=year, allowance=t.days_per_year + rnd.choice([0, 0, 2])))
    Attendance.objects.bulk_create(records, batch_size=5000)
    LeaveRequest.objects.bulk_create(requests, batch_size=2000)
    LeaveBalance.objects.bulk_create(balances, batch_size=2000)
    return len(records), len(requests)


def test_attendance_report_with_a_year_of_data(client_for):
    admin, manager, _n, _m = build()
    users = list(User.objects.filter(email__startswith="perf", role__in=["manager", "staff"]).order_by("pk"))
    n_records, n_requests = build_attendance(users, admin)
    today = office_today()
    year = {"from": (today - timedelta(days=364)).isoformat(), "to": today.isoformat()}
    month = {"from": today.replace(day=1).isoformat(), "to": today.isoformat()}
    urls = {
        "attendance, a year": ("/api/v1/reports/attendance/", year),
        "attendance, this month": ("/api/v1/reports/attendance/", month),
        "attendance PDF": ("/api/v1/reports/attendance/export/", {**year, "file": "pdf"}),
        "attendance Excel": ("/api/v1/reports/attendance/export/", {**year, "file": "xlsx"}),
    }
    print(f"\n{n_records} check-ins, {n_requests} leave requests, {PEOPLE} people ({connection.vendor})")
    for who, user, lang in (("admin", admin, "en"), ("manager", manager, "en"), ("admin", admin, "ur"), ("manager", manager, "ur")):
        who = f"{who} ({lang})"
        client = client_for(user)
        client.get(urls["attendance, this month"][0], month)  # warm up
        for name, (url, params) in urls.items():
            with CaptureQueriesContext(connection) as ctx:
                start = time.perf_counter()
                res = client.get(url, params, HTTP_ACCEPT_LANGUAGE=lang)
                took = time.perf_counter() - start
            assert res.status_code == 200, (name, res.status_code)
            size = f", {len(res.content) // 1024} KB" if "export" in url else ""
            print(f"  {who:<13} {name:<26} {took * 1000:7.0f} ms  {len(ctx):2d} queries{size}")
            assert took < 5, f"{name} took {took:.1f}s"
