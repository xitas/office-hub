"""Reports, slice 3: field visits completed vs. planned (by person, purpose and outcome; check-ins by the person
responsible; pending and rejected visits left out) and errands done and not done (by runner and kind, waiting ones
under "nobody yet", on time by the due time; only errands the viewer may see). Scope per role, exports in both
languages with the audit log, and query counts that don't grow with the data."""
import io
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from openpyxl import load_workbook

from apps.core.models import AuditLog
from apps.core.office_time import office_today
from apps.errands.models import Errand
from apps.visits.models import Visit, VisitCheck, VisitReport

pytestmark = pytest.mark.django_db

VISITS = "/api/v1/reports/field-visits/"
ERRANDS = "/api/v1/reports/errands/"


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {
        "admin": admin, "manager": manager, "staff": staff,
        "colleague": make_user("colleague@test.com", full_name="Sara Colleague"),
        "ops": make_user("ops.person@test.com", department="ops", full_name="Omar Ops"),
        "ops_manager": make_user("ops.manager@test.com", role="manager", department="ops", full_name="Olga Manager"),
    }


def visit(who, days, status="planned", purpose="meeting", hours=1):
    start = timezone.now() + timedelta(days=days)
    return Visit.objects.create(title=f"{status} {days}", place_name="Site", purpose=purpose, assigned_to=who, status=status,
                                start=start, end=start + timedelta(hours=hours))


def period(days_back=20, days_ahead=10):
    today = office_today()
    return {"from": (today - timedelta(days=days_back)).isoformat(), "to": (today + timedelta(days=days_ahead)).isoformat()}


def test_visits_completed_vs_planned(client_for, people):
    s, c = people["staff"], people["colleague"]
    done = visit(s, -5, "done")
    VisitCheck.objects.create(visit=done, user=s, checked_in_at=done.start, in_location="declined")
    VisitReport.objects.create(visit=done, outcome="good", written_by=s)
    done2 = visit(s, -4, "done", purpose="delivery")
    VisitCheck.objects.create(visit=done2, user=c, checked_in_at=done2.start, in_location="declined")  # a companion's: not counted
    VisitReport.objects.create(visit=done2, outcome="not_met", written_by=s)
    visit(s, -3, "cancelled")
    visit(s, -2, "planned")  # past its end, never closed
    visit(s, 3, "planned")  # upcoming
    visit(s, -2, "pending")
    visit(s, -2, "rejected")
    visit(s, -40, "done")  # before the period
    visit(people["ops"], -2, "done")  # another department
    res = client_for(people["manager"]).get(VISITS, period())
    assert res.status_code == 200
    staff = next(p for p in res.data["people"] if p["name"] == "Staff")
    assert (staff["scheduled"], staff["done"], staff["cancelled"], staff["not_closed"], staff["upcoming"]) == (5, 2, 1, 1, 1)
    assert staff["completion"] == 0.5 and staff["checked_in"] == 1 and staff["reported"] == 2 and staff["check_in_rate"] == 0.5
    purposes = {p["purpose"]: p for p in res.data["purposes"]}
    assert purposes["meeting"]["scheduled"] == 4 and purposes["delivery"]["done"] == 1 and purposes["site"]["scheduled"] == 0
    outcomes = {o["outcome"]: o for o in res.data["outcomes"]}
    assert outcomes["good"]["count"] == 1 and outcomes["not_met"]["share"] == 0.5 and outcomes["follow_up"]["share"] == 0
    assert res.data["totals"]["scheduled"] == 5
    assert client_for(people["admin"]).get(VISITS, period()).data["totals"]["scheduled"] == 6
    assert client_for(people["staff"]).get(VISITS).status_code == 403


def errand(who, days, status="assigned", kind="courier", by=None, department=None, finished_delta=None):
    due = timezone.now() + timedelta(days=days)
    return Errand.objects.create(title=f"{status} {days}", kind=kind, place_name="Bank", assigned_to=who, status=status, due_at=due,
                                 requested_by=by or who, department=department or (who.department if who else None),
                                 finished_at=due + finished_delta if finished_delta is not None else None)


def test_errands_done_and_not_done(client_for, people):
    s, o, sales = people["staff"], people["ops"], people["staff"].department
    errand(s, -5, "done", finished_delta=timedelta(hours=-1))  # on time
    errand(s, -4, "done", kind="bank", finished_delta=timedelta(hours=3))  # late
    errand(s, -3, "failed")
    errand(s, -2, "cancelled")
    errand(s, -1, "on_the_way")  # overdue
    errand(s, 2, "assigned")  # still open, not overdue
    errand(None, 1, "open", by=s, department=sales)  # waiting for someone in Sales
    errand(o, -1, "done", department=sales, finished_delta=timedelta(hours=-1))  # an admin gave a Sales errand to Ops
    errand(o, -1, "done", finished_delta=timedelta(hours=-1))  # Ops' own
    res = client_for(people["manager"]).get(ERRANDS, period())
    assert res.status_code == 200
    staff = next(p for p in res.data["people"] if p["name"] == "Staff")
    assert (staff["asked"], staff["done"], staff["failed"], staff["cancelled"], staff["open"], staff["overdue"], staff["on_time"]) == (6, 2, 1, 1, 2, 1, 1)
    assert staff["success"] == round(2 / 3, 4) and staff["on_time_rate"] == 0.5
    nobody = next(p for p in res.data["people"] if p["name"] is None)
    assert nobody["asked"] == 1 and nobody["open"] == 1
    assert res.data["totals"]["asked"] == 7  # not Ops' errands
    kinds = {k["kind"]: k for k in res.data["kinds"]}
    assert kinds["bank"]["done"] == 1 and kinds["courier"]["asked"] == 6
    # The Ops manager sees their own department's errand, not the Sales errand their person ran.
    ops = client_for(people["ops_manager"]).get(ERRANDS, period()).data
    assert next(p for p in ops["people"] if p["name"] == "Omar Ops")["asked"] == 1
    assert client_for(people["admin"]).get(ERRANDS, period()).data["totals"]["asked"] == 9
    one = client_for(people["manager"]).get(ERRANDS, {**period(), "person": s.pk}).data
    assert [p["name"] for p in one["people"]] == ["Staff"]  # no "nobody yet" row for one person


def test_report_visits_are_within_what_the_viewer_may_see(people, make_user):
    """Visits are filtered by the person responsible directly (no visibility subquery): only right while a report's
    people are always ones whose visits the viewer may see."""
    from apps.reports.scope import scope_for
    from apps.visits.rules import visible_visits

    viewers = {**people, "solo": make_user("solo.manager@test.com", role="manager", department=None)}
    for who in ("manager", "admin", "solo"):
        for p in scope_for(viewers[who], {}).people:
            v = visit(p, -1)
            assert visible_visits(viewers[who]).filter(pk=v.pk).exists(), (who, p.email)


def test_field_report_exports(client_for, people):
    s = people["staff"]
    done = visit(s, -2, "done")
    VisitReport.objects.create(visit=done, outcome="follow_up", written_by=s)
    errand(s, -1, "done", finished_delta=timedelta(hours=-1))
    manager = client_for(people["manager"])
    for url in (VISITS, ERRANDS):
        for lang in ("en", "ur"):
            pdf = manager.get(f"{url}export/", {**period(), "file": "pdf"}, HTTP_ACCEPT_LANGUAGE=lang)
            assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and (lang == "en" or b"NotoNastaliqUrdu" in pdf.content)
            wb = load_workbook(io.BytesIO(manager.get(f"{url}export/", {**period(), "file": "xlsx"}, HTTP_ACCEPT_LANGUAGE=lang).content))
            assert all(ws.sheet_view.rightToLeft == (lang == "ur") for ws in wb.worksheets)
    assert client_for(people["staff"]).get(f"{ERRANDS}export/", {"file": "xlsx"}).status_code == 403
    assert set(AuditLog.objects.filter(action="export").values_list("changes__records", flat=True)) == {"field visits report", "errands report"}


def test_field_report_queries_do_not_grow(client_for, people, make_user):
    admin = client_for(people["admin"])

    def count(url, params):
        admin.get(url, params)
        with CaptureQueriesContext(connection) as ctx:
            res = admin.get(url, params)
        assert res.status_code == 200
        return len(ctx)

    def add(i):
        person = make_user(f"p{i}@test.com", department="ops" if i % 2 else "sales")
        for k, status in enumerate(["done", "cancelled", "planned", "done"]):
            v = visit(person, -k - 1, status, purpose=["meeting", "site", "delivery", "other"][k])
            if status == "done":
                VisitCheck.objects.create(visit=v, user=person, checked_in_at=v.start, in_location="declined")
                VisitReport.objects.create(visit=v, outcome=["good", "follow_up"][k % 2], written_by=person)
            errand(person, -k - 1, ["done", "failed", "assigned", "cancelled"][k], kind=["courier", "bank", "pickup", "other"][k],
                   finished_delta=timedelta(hours=1) if k == 0 else None)

    urls = {"visits": (VISITS, period()), "errands": (ERRANDS, period()), "visits pdf": (f"{VISITS}export/", {**period(), "file": "pdf"}),
            "errands xlsx": (f"{ERRANDS}export/", {**period(), "file": "xlsx"})}
    add(0)
    small = {k: count(*v) for k, v in urls.items()}
    for i in range(1, 7):
        add(i)
    assert {k: count(*v) for k, v in urls.items()} == small
