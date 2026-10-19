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
