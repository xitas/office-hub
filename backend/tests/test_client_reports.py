"""Reports, slice 2: client interactions per week or month (office days and the office's week start; calls,
meetings, emails, WhatsApp and visit reports, not notes or vendors; only what the viewer sees) and the lead pipeline
(leads added in the period, how far they got, win rate and conversion, status changes and days to win). Scope per
role, exports in both languages with the audit log, and query counts that don't grow with the data."""
import io
from datetime import date, datetime, time, timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from openpyxl import load_workbook

from apps.contacts.models import Company, Contact, ContactStatusChange
from apps.core.models import AuditLog, OrganizationSettings
from apps.core.office_time import office_today, office_tz
from apps.reports.client_reports import buckets_for
from apps.timeline.models import TimelineEntry
from apps.vendors.models import Vendor

pytestmark = pytest.mark.django_db

INTERACTIONS = "/api/v1/reports/client-interactions/"
PIPELINE = "/api/v1/reports/lead-pipeline/"


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {
        "admin": admin, "manager": manager, "staff": staff,
        "ops": make_user("ops.person@test.com", department="ops", full_name="Omar Ops"),
    }


def at(day, hh, mm=0):
    return datetime.combine(day, time(hh, mm), tzinfo=office_tz())


def log(kind, who, when, contact=None, company=None, vendor=None):
    return TimelineEntry.objects.create(kind=kind, contact=contact, company=company, vendor=vendor, summary="s", occurred_at=when, created_by=who,
                                        details={"direction": "out", "outcome": "connected"} if kind == "call" else {})


def test_buckets_follow_the_office_week_start_and_months():
    OrganizationSettings.objects.update_or_create(pk=1, defaults={"week_start": 1})
    monday = buckets_for(date(2026, 10, 1), date(2026, 10, 14), "week")  # Thu 1 Oct … Wed 14 Oct
    assert monday == [(date(2026, 10, 1), date(2026, 10, 4)), (date(2026, 10, 5), date(2026, 10, 11)), (date(2026, 10, 12), date(2026, 10, 14))]
    OrganizationSettings.objects.filter(pk=1).update(week_start=0)
    settings = OrganizationSettings.objects.get(pk=1)
    settings.save()  # (saving refreshes the cached settings)
    assert buckets_for(date(2026, 10, 1), date(2026, 10, 11), "week")[:2] == [(date(2026, 10, 1), date(2026, 10, 3)), (date(2026, 10, 4), date(2026, 10, 10))]
    assert buckets_for(date(2026, 9, 15), date(2026, 11, 2), "month") == [
        (date(2026, 9, 15), date(2026, 9, 30)), (date(2026, 10, 1), date(2026, 10, 31)), (date(2026, 11, 1), date(2026, 11, 2))]


def test_interactions_per_week_kind_and_person(client_for, people):
    today = office_today()
    s, m, o = people["staff"], people["manager"], people["ops"]
    hira = Contact.objects.create(first_name="Hira", assigned_to=s)
    saba = Company.objects.create(name="Saba", assigned_to=s)
    theirs = Contact.objects.create(first_name="Ops lead", assigned_to=o)
    d = today - timedelta(days=3)
    log("call", s, at(d, 23, 30), contact=hira)  # late evening: that office day
    log("meeting", s, at(d, 10), company=saba)
    log("visit", m, at(d, 11), contact=hira)
    log("note", s, at(d, 12), contact=hira)  # internal: not counted
    log("call", s, at(d, 13), vendor=Vendor.objects.create(name="TCS", phone="042 111"))  # a vendor, not a client
    log("call", o, at(d, 14), contact=theirs)  # another department
    log("email", s, at(today - timedelta(days=200), 9), contact=hira)  # before the period
    res = client_for(people["manager"]).get(INTERACTIONS, {"from": (today - timedelta(days=20)).isoformat(), "to": today.isoformat()})
    assert res.status_code == 200
    t = res.data["totals"]
    assert t["total"] == 3 and t["counts"]["call"] == 1 and t["counts"]["meeting"] == 1 and t["counts"]["visit"] == 1 and t["clients"] == 2
    assert sum(b["total"] for b in res.data["buckets"]) == 3 and res.data["buckets"][0]["from"] == today - timedelta(days=20)
    by = {p["name"]: p for p in res.data["people"]}
    assert by["Staff"]["total"] == 2 and by["Staff"]["clients"] == 2 and by["Manager"]["counts"]["visit"] == 1
    assert "Omar Ops" not in by
    month = client_for(people["admin"]).get(INTERACTIONS, {"from": (today - timedelta(days=20)).isoformat(), "to": today.isoformat(), "by": "month"}).data
    assert month["by"] == "month" and month["totals"]["total"] == 4  # admins: the other department too
    assert client_for(people["manager"]).get(INTERACTIONS, {"by": "day"}).status_code == 400
    assert client_for(people["staff"]).get(INTERACTIONS).status_code == 403


def _lead(name, who, created, *path):
    """A lead added at `created`, then moved through `path` ((status, when), ...)."""
    c = Contact.objects.create(first_name=name, assigned_to=who, status=path[-1][0] if path else "new")
    Contact.objects.filter(pk=c.pk).update(created_at=created)
    ContactStatusChange.objects.create(contact=c, from_status="", to_status="new", changed_at=created)
    previous = "new"
    for status, when in path:
        ContactStatusChange.objects.create(contact=c, from_status=previous, to_status=status, changed_at=when)
        previous = status
    return c


def test_pipeline_funnel_rates_moves_and_days_to_win(client_for, people):
    today = office_today()
    s, o = people["staff"], people["ops"]
    a = at(today - timedelta(days=30), 10)
    _lead("Won", s, a, ("contacted", a + timedelta(days=2)), ("in_discussion", a + timedelta(days=5)), ("won", a + timedelta(days=10)))
    _lead("Lost", s, a, ("contacted", a + timedelta(days=1)), ("lost", a + timedelta(days=4)))
    _lead("Talking", s, a, ("in_discussion", a + timedelta(days=3)))  # skipped "Contacted": still counts as reached
    _lead("New", s, a)
    _lead("Old one", s, at(today - timedelta(days=90), 10), ("won", a + timedelta(days=6)))  # added before: a move and a win, not in the cohort
    _lead("Ops", o, a, ("won", a + timedelta(days=2)))  # another department
    res = client_for(people["manager"]).get(PIPELINE, {"from": (today - timedelta(days=40)).isoformat(), "to": today.isoformat()})
    assert res.status_code == 200
    f = res.data["funnel"]
    assert (f["created"], f["contacted"], f["in_discussion"], f["won"], f["lost"], f["open"]) == (4, 3, 2, 1, 1, 2)
    assert f["win_rate"] == 0.5 and f["conversion"] == 0.25
    moves = {(m["from"], m["to"]): m["count"] for m in res.data["moves"]}
    assert moves[("new", "contacted")] == 2 and moves[("new", "won")] == 1 and ("new", "in_discussion") in moves
    assert res.data["won_in_period"] == 2  # "Won" and "Old one"
    assert res.data["average_days_to_win"] == pytest.approx((10 + 90 - 30 + 6) / 2, abs=0.1)
    staff = next(p for p in res.data["people"] if p["name"] == "Staff")
    assert staff["created"] == 4 and staff["won"] == 1
    everyone = client_for(people["admin"]).get(PIPELINE, {"from": (today - timedelta(days=40)).isoformat(), "to": today.isoformat()}).data
    assert everyone["funnel"]["created"] == 5 and everyone["funnel"]["won"] == 2
    assert client_for(people["staff"]).get(PIPELINE).status_code == 403


def test_client_report_exports(client_for, people):
    today = office_today()
    s = people["staff"]
    hira = Contact.objects.create(first_name="=Hira", assigned_to=s)  # a name that starts like a formula
    log("call", s, at(today - timedelta(days=2), 10), contact=hira)
    _lead("Won", s, at(today - timedelta(days=5), 10), ("won", at(today - timedelta(days=1), 10)))
    manager = client_for(people["manager"])
    period = {"from": (today - timedelta(days=30)).isoformat(), "to": today.isoformat()}
    for url, extra in ((INTERACTIONS, {"by": "month"}), (PIPELINE, {})):
        for lang in ("en", "ur"):
            pdf = manager.get(f"{url}export/", {**period, **extra, "file": "pdf"}, HTTP_ACCEPT_LANGUAGE=lang)
            assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
            assert lang == "en" or b"NotoNastaliqUrdu" in pdf.content
            xlsx = manager.get(f"{url}export/", {**period, **extra, "file": "xlsx"}, HTTP_ACCEPT_LANGUAGE=lang)
            wb = load_workbook(io.BytesIO(xlsx.content))
            assert all(ws.sheet_view.rightToLeft == (lang == "ur") for ws in wb.worksheets)
    assert client_for(people["staff"]).get(f"{PIPELINE}export/", {"file": "pdf"}).status_code == 403
    logged = set(AuditLog.objects.filter(action="export").values_list("changes__records", flat=True))
    assert logged == {"client interactions report", "lead pipeline report"}


def test_client_report_queries_do_not_grow(client_for, people, make_user):
    admin = client_for(people["admin"])
    today = office_today()
    period = {"from": (today - timedelta(days=200)).isoformat(), "to": today.isoformat()}

    def count(url, params):
        admin.get(url, params)
        with CaptureQueriesContext(connection) as ctx:
            res = admin.get(url, params)
        assert res.status_code == 200
        return len(ctx)

    def add(i):
        person = make_user(f"p{i}@test.com", department="ops" if i % 2 else "sales")
        for k in range(5):
            when = at(today - timedelta(days=k * 30 + 3), 10)
            lead = _lead(f"L{i}-{k}", person, when, ("contacted", when + timedelta(days=1)), *((("won", when + timedelta(days=4)),) if k % 2 else ()))
            log(["call", "meeting", "email", "whatsapp", "visit"][k], person, when, contact=lead)

    urls = {
        "interactions by week": (INTERACTIONS, period), "interactions by month": (INTERACTIONS, {**period, "by": "month"}),
        "pipeline": (PIPELINE, period), "interactions xlsx": (f"{INTERACTIONS}export/", {**period, "file": "xlsx"}),
        "pipeline pdf": (f"{PIPELINE}export/", {**period, "file": "pdf"}),
    }
    add(0)
    small = {k: count(*v) for k, v in urls.items()}
    for i in range(1, 7):
        add(i)
    assert {k: count(*v) for k, v in urls.items()} == small


def test_report_people_are_always_within_what_the_viewer_may_see(people, make_user):
    """The pipeline filters status changes by the report's people directly (no visibility subquery): that's only
    right while a report's scope never reaches beyond the viewer's visible contacts."""
    from apps.contacts.visibility import visible_contacts
    from apps.reports.scope import scope_for

    viewers = {**people, "solo": make_user("solo.manager@test.com", role="manager", department=None)}  # a manager with no department
    for who in ("manager", "admin", "solo"):
        viewer = viewers[who]
        scope = scope_for(viewer, {})
        for p in scope.people:
            lead = Contact.objects.create(first_name=f"Lead of {p.email}", assigned_to=p)
            assert visible_contacts(viewer).filter(pk=lead.pk).exists(), (who, p.email)
