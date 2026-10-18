"""Checking in and out at field visits: who may and when, "no location", accuracy and distance from the pin, who
sees coordinates (per role, in the API), attendance's field status, notifications with Urdu time words, the
missed check-in reminder, the 90-day removal (one audit entry, no coordinates in the audit log), query counts."""
import io
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.attendance.models import Attendance
from apps.contacts.models import Company
from apps.core.models import AuditLog
from apps.core.office_time import office_today
from apps.notifications.models import Notification
from apps.visits import checks
from apps.visits.models import Visit, VisitCheck

pytestmark = pytest.mark.django_db

URL = "/api/v1/visits/"
PIN = (Decimal("31.520400"), Decimal("74.358700"))
HERE = {"location": "recorded", "latitude": "31.5212", "longitude": "74.3590", "accuracy": 18.4}  # ~90 m from the pin


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {
        "admin": admin, "manager": manager, "staff": staff,
        "colleague": make_user("colleague@test.com", full_name="Sara Colleague", language="ur"),
        "ops": make_user("ops.person@test.com", department="ops", full_name="Omar Ops"),
        "ops_manager": make_user("ops.manager@test.com", role="manager", department="ops", full_name="Olga Manager"),
    }


@pytest.fixture
def visit(people):
    company = Company.objects.create(name="Clifton Retail", assigned_to=people["staff"])
    now = timezone.now()
    v = Visit.objects.create(title="Quarterly review", company=company, assigned_to=people["staff"], status="planned",
                             start=now + timedelta(minutes=30), end=now + timedelta(minutes=90), latitude=PIN[0], longitude=PIN[1],
                             created_by=people["manager"])
    v.companions.set([people["colleague"]])
    return v


def test_who_checks_in_and_when(client_for, people, visit, django_capture_on_commit_callbacks):
    staff, colleague, manager = (client_for(people[k]) for k in ("staff", "colleague", "manager"))
    url = f"{URL}{visit.pk}/"
    assert manager.post(f"{url}check-in/", HERE, format="json").status_code == 403  # not going
    assert staff.post(f"{url}check-in/", {"location": "recorded"}, format="json").status_code == 400  # coordinates needed
    assert staff.post(f"{url}check-out/", {"location": "declined"}, format="json").status_code == 400  # not checked in
    with django_capture_on_commit_callbacks(execute=True):
        res = staff.post(f"{url}check-in/", HERE, format="json")
    assert res.status_code == 200 and not res.data["can_check_in"]
    mine = res.data["checks"][0]
    assert mine["in_location"] == "recorded" and mine["in"]["accuracy"] == 18 and 60 < mine["in"]["distance_m"] < 120
    assert staff.post(f"{url}check-in/", HERE, format="json").status_code == 400  # once
    # Declining still checks in ("no location"); the attendance day starts as a field visit for someone not yet in.
    Attendance.objects.create(user=people["colleague"], date=office_today(), check_in=timezone.now() - timedelta(hours=2), mode="office")
    res = colleague.post(f"{url}check-in/", {"location": "declined"}, format="json")
    assert res.status_code == 200
    theirs = next(c for c in res.data["checks"] if c["user"] == people["colleague"].pk)
    assert theirs["in_location"] == "declined" and theirs["in"] is None
    assert Attendance.objects.get(user=people["staff"]).mode == "field"
    assert Attendance.objects.get(user=people["colleague"]).mode == "office"  # already in the office: left as is
    with django_capture_on_commit_callbacks(execute=True):
        res = staff.post(f"{url}check-out/", {"location": "unavailable"}, format="json")
    assert res.data["checks"][0]["out_location"] == "unavailable"
    arrived = Notification.objects.get(message_key="visit_checked_in")  # whoever planned it for them
    assert arrived.recipient == people["manager"] and arrived.title == "Staff arrived: Quarterly review"
    assert Notification.objects.filter(message_key="visit_checked_out", recipient=people["manager"]).exists()
    # Outside the window (more than two hours before the start): refused.
    later = Visit.objects.create(title="Next week", place_name="Site", assigned_to=people["staff"], status="planned",
                                 start=timezone.now() + timedelta(days=7), end=timezone.now() + timedelta(days=7, hours=1))
    assert staff.post(f"{URL}{later.pk}/check-in/", HERE, format="json").status_code == 403
    # Times and whether a location was shared are audited; coordinates never are.
    entries = AuditLog.objects.filter(object_id=str(visit.pk), description__in=["Checked in", "Checked out"])
    assert entries.count() == 3 and not any("31.52" in str(e.changes) for e in entries)


def test_location_visible_only_to_the_person_their_managers_and_admins(client_for, people, visit):
    checks.check_in(people["staff"], visit, {"location": "recorded", "latitude": Decimal("31.5212"), "longitude": Decimal("74.359"), "accuracy": 10})
    checks.check_in(people["colleague"], visit, {"location": "recorded", "latitude": Decimal("31.53"), "longitude": Decimal("74.36"), "accuracy": 5})
    visit.companions.add(people["ops"])
    seen = lambda who: {c["user_name"]: c["in"] for c in client_for(people[who]).get(f"{URL}{visit.pk}/").data["checks"]}  # noqa: E731
    assert all(seen("staff")[n] is None for n in ["Sara Colleague"]) and seen("staff")["Staff"] is not None  # own only
    assert seen("colleague")["Staff"] is None and seen("colleague")["Sara Colleague"] is not None
    assert all(seen("manager").values())  # the department's manager
    assert all(seen("admin").values())
    assert not any(seen("ops").values())  # a companion from another department sees neither
    assert client_for(people["ops_manager"]).get(f"{URL}{visit.pk}/").status_code == 404  # can't see the visit at all
    # Lists hide them the same way.
    rows = client_for(people["colleague"]).get(URL).data
    assert [c["in"] for v in rows for c in v["checks"] if c["user_name"] == "Staff"] == [None]


def test_missed_check_in_reminder_with_urdu_time_words(people, django_capture_on_commit_callbacks):
    now = timezone.now()
    late = Visit.objects.create(title="Collect cheque", place_name="Liberty Market", assigned_to=people["colleague"], status="planned",
                                start=now - timedelta(minutes=40), end=now + timedelta(minutes=20))
    Visit.objects.create(title="Just started", place_name="Site", assigned_to=people["staff"], status="planned",
                         start=now - timedelta(minutes=10), end=now + timedelta(minutes=50))
    done = Visit.objects.create(title="Checked in", place_name="Site", assigned_to=people["staff"], status="planned",
                                start=now - timedelta(minutes=50), end=now + timedelta(minutes=10))
    VisitCheck.objects.create(visit=done, user=people["staff"], checked_in_at=now - timedelta(minutes=45), in_location="declined")
    with django_capture_on_commit_callbacks(execute=True):
        assert checks.send_missed_check_in(now) == 1
    assert checks.send_missed_check_in(now) == 0  # once
    note = Notification.objects.get(message_key="visit_check_in_missed")
    assert note.recipient == people["colleague"] and note.title == "ابھی تک آمد درج نہیں: Collect cheque"
    assert any(w in note.body for w in ("صبح", "دوپہر", "شام", "رات"))
    assert late.pk


def test_old_locations_removed_after_90_days_in_one_audit_entry(people, visit):
    old_visit = Visit.objects.create(title="Old", place_name="Site", assigned_to=people["staff"], status="done",
                                     start=timezone.now() - timedelta(days=100), end=timezone.now() - timedelta(days=100) + timedelta(hours=1))
    old = VisitCheck.objects.create(visit=old_visit, user=people["staff"], checked_in_at=timezone.now() - timedelta(days=100),
                                    in_location="recorded", in_latitude=PIN[0], in_longitude=PIN[1], in_accuracy=12,
                                    checked_out_at=timezone.now() - timedelta(days=100) + timedelta(hours=1), out_location="recorded",
                                    out_latitude=PIN[0], out_longitude=PIN[1], out_accuracy=9)
    old2 = VisitCheck.objects.create(visit=old_visit, user=people["colleague"], checked_in_at=timezone.now() - timedelta(days=95),
                                     in_location="recorded", in_latitude=PIN[0], in_longitude=PIN[1])
    declined = VisitCheck.objects.create(visit=visit, user=people["ops"], checked_in_at=timezone.now() - timedelta(days=120), in_location="declined")
    recent = VisitCheck.objects.create(visit=visit, user=people["staff"], checked_in_at=timezone.now() - timedelta(days=89),
                                       in_location="recorded", in_latitude=PIN[0], in_longitude=PIN[1])
    assert checks.remove_old_locations() == 2
    old.refresh_from_db()
    assert old.in_latitude is None and old.out_longitude is None and old.in_accuracy is None and old.location_removed_at
    assert old.checked_in_at and old.in_location == "recorded"  # the times and that it was shared stay
    recent.refresh_from_db()
    assert recent.in_latitude == PIN[0]
    entry = AuditLog.objects.get(description="Removed visit locations older than 90 days")
    assert entry.changes["check_ins"] == 2 and entry.actor is None
    assert checks.remove_old_locations() == 0 and AuditLog.objects.filter(description__startswith="Removed visit locations").count() == 1
    declined.refresh_from_db()
    assert declined.location_removed_at is None and old2.pk


def test_visit_lists_with_checks_do_not_grow(client_for, people, make_user):
    manager = client_for(people["manager"])
    now = timezone.now()

    params = {"scope": "team", "from": office_today().isoformat(), "to": office_today().isoformat()}

    def count():
        manager.get(URL, params)  # warm the settings cache
        with CaptureQueriesContext(connection) as ctx:
            res = manager.get(URL, params)
        assert res.status_code == 200
        return len(ctx), len(res.data)

    def add(i):
        person = make_user(f"p{i}@test.com")
        v = Visit.objects.create(title=f"V{i}", place_name="Site", assigned_to=person, status="planned", start=now, end=now + timedelta(hours=1),
                                 latitude=PIN[0], longitude=PIN[1])
        v.companions.set([people["staff"]])
        VisitCheck.objects.create(visit=v, user=person, checked_in_at=now, in_location="recorded", in_latitude=PIN[0], in_longitude=PIN[1])
        VisitCheck.objects.create(visit=v, user=people["staff"], checked_in_at=now, in_location="declined")

    add(0)
    small = count()
    for i in range(1, 8):
        add(i)
    grown = count()
    assert grown[0] == small[0] and grown[1] > small[1]


def test_seed_creates_check_ins(db):
    from django.core.management import call_command

    call_command("seed_demo", stdout=io.StringIO())
    assert VisitCheck.objects.filter(in_location="recorded", in_latitude__isnull=False).exists()
    assert VisitCheck.objects.filter(in_location="declined").exists()
    assert VisitCheck.objects.filter(location_removed_at__isnull=False, in_latitude__isnull=True).exists()
