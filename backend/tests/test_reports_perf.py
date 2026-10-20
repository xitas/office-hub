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
