"""Reports, final review: no Phase 6 endpoint's query count grows with the data.

Every report and both export formats, plus the people list, for an admin (everyone, and one department) and a manager
(their department, and one person), measured with a little data and again with seven times the people and records of
every kind the reports count (tasks, client interactions, leads, field visits, errands, attendance and leave)."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import Department
from apps.contacts.models import Contact
from apps.core.office_time import office_today
from apps.leave.models import LeaveType
from apps.visits.models import VisitCheck, VisitReport
from tests.test_attendance_reports import check_in, leave
from tests.test_client_reports import _lead, at, log
from tests.test_field_reports import errand, visit
from tests.test_reports import task

pytestmark = pytest.mark.django_db

BASE = "/api/v1/reports"
REPORTS = ["task-completion", "overdue-tasks", "client-interactions", "lead-pipeline", "field-visits", "errands", "attendance"]


def add(i, make_user, annual):
    """One more person with a bit of everything the reports count."""
    today = office_today()
    person = make_user(f"p{i}@test.com", department="ops" if i % 2 else "sales")
    client = Contact.objects.create(first_name=f"Client {i}", assigned_to=person)
    for k in range(3):
        due = today - timedelta(days=3 + k * 7)
        task(f"T{i}-{k}", [person], due, done_at=at(due, 12) if k % 2 else None, priority="high" if k else "low")
        when = at(today - timedelta(days=4 + k * 6), 10)
        _lead(f"L{i}-{k}", person, when, ("contacted", when + timedelta(days=1)), *((("won", when + timedelta(days=2)),) if k % 2 else ()))
        log(["call", "meeting", "email"][k], person, when, contact=client)
        v = visit(person, -2 - k, ["done", "cancelled", "planned"][k], purpose=["meeting", "site", "delivery"][k])
        if v.status == "done":
            VisitCheck.objects.create(visit=v, user=person, checked_in_at=v.start, in_location="declined")
            VisitReport.objects.create(visit=v, outcome="good", written_by=person)
        errand(person, -1 - k, ["done", "failed", "assigned"][k], kind=["courier", "bank", "pickup"][k],
               finished_delta=timedelta(hours=1) if k < 2 else None)
        day = today - timedelta(days=1 + k * 7)
        if day.weekday() < 5:
            check_in(person, day, 9 + k, mode=["office", "remote", "field"][k])
    first = today - timedelta(days=10)
    leave(person, annual, first, first, Decimal("0.5"), half_day="morning")
    return person


def test_no_phase_6_endpoint_grows_with_the_data(client_for, admin, manager, staff, make_user):
    today = office_today()
    period = {"from": (today - timedelta(days=40)).isoformat(), "to": today.isoformat()}
    annual = LeaveType.objects.create(name="Annual", days_per_year=Decimal("20"))
    add(0, make_user, annual)
    task("Staff's own", [staff], today - timedelta(days=2))  # the one person has data too (an empty list skips a prefetch)
    sales = Department.objects.get(name="Sales")
    viewers = {
        "admin, everyone": (admin, {}),
        "admin, one department": (admin, {"department": sales.pk}),
        "manager": (manager, {}),
        "manager, one person": (manager, {"person": staff.pk}),
    }
    requests = [("people", "/api/v1/reports/people/", {})]
    for report in REPORTS:
        params = {} if report == "overdue-tasks" else dict(period)
        requests.append((report, f"{BASE}/{report}/", params))
        for fmt in ("pdf", "xlsx"):
            requests.append((f"{report} {fmt}", f"{BASE}/{report}/export/", {**params, "file": fmt}))

    def counts():
        out = {}
        for who, (user, scope) in viewers.items():
            client = client_for(user)
            client.get(f"{BASE}/people/")  # warm the settings cache
            for name, url, params in requests:
                with CaptureQueriesContext(connection) as ctx:
                    res = client.get(url, {**params, **scope})
                assert res.status_code == 200, (who, name, res.status_code)
                out[(who, name)] = len(ctx)
        return out

    small = counts()
    for i in range(1, 8):
        add(i, make_user, annual)
    for k in range(5):  # and more for the one person
        task(f"Staff's own {k}", [staff], today - timedelta(days=3 + k), priority="urgent")
        log("call", staff, at(today - timedelta(days=2 + k), 10), contact=Contact.objects.create(first_name=f"S{k}", assigned_to=staff))
        errand(staff, -1 - k, "done", finished_delta=timedelta(hours=-1))
    grown = counts()
    assert {k: v for k, v in grown.items() if v != small[k]} == {}, {k: (small[k], v) for k, v in grown.items() if v != small[k]}
    assert len(small) == 4 * (1 + 3 * len(REPORTS))
