import io
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.contacts.models import Company, Contact, ContactStatusChange, Tag
from apps.core.models import AuditLog

pytestmark = pytest.mark.django_db

CONTACTS = "/api/v1/contacts/"
PIPELINE = "/api/v1/contacts/pipeline/"


@pytest.fixture
def people(make_user, admin, manager, staff):
    return {
        "admin": admin,
        "manager": manager,
        "staff": staff,
        "colleague": make_user("colleague@test.com"),
        "outsider": make_user("ops.person@test.com", department="ops"),
    }


@pytest.fixture
def board(people):
    acme = Company.objects.create(name="Acme", assigned_to=people["staff"])
    vip = Tag.objects.create(name="VIP")

    def make(first, owner, status="new", **extra):
        return Contact.objects.create(first_name=first, assigned_to=people[owner], status=status, **extra)

    c = {
        "mine_new": make("MineNew", "staff", company=acme, city="Lahore"),
        "mine_won": make("MineWon", "staff", status="won", city="Karachi"),
        "colleague": make("Colleague", "colleague", status="contacted", city="Lahore"),
        "manager": make("Manager", "manager", status="in_discussion"),
        "outsider": make("Outsider", "outsider", status="lost", city="Lahore"),
    }
    c["mine_new"].tags.add(vip)
    return c


def column(res, status):
    return next(col for col in res.data["columns"] if col["status"] == status)


def card_names(res, status):
    return sorted(card["full_name"] for card in column(res, status)["cards"])


# ---------------------------------------------------------------- board contents


def test_board_has_all_columns_in_order_with_counts(client_for, people, board):
    res = client_for(people["admin"]).get(PIPELINE)
    assert [c["status"] for c in res.data["columns"]] == ["new", "contacted", "in_discussion", "won", "lost"]
    assert [c["count"] for c in res.data["columns"]] == [1, 1, 1, 1, 1]
    assert res.data["total"] == 5
    card = column(res, "new")["cards"][0]
    assert card["full_name"] == "MineNew" and card["company_name"] == "Acme" and card["tags"] == ["VIP"]
    assert card["assigned_to_name"] == people["staff"].full_name and card["status_changed_at"]


def test_board_scoping_by_role(client_for, people, board):
    staff = client_for(people["staff"]).get(PIPELINE)
    assert staff.data["total"] == 2 and card_names(staff, "won") == ["MineWon"]
    manager = client_for(people["manager"]).get(PIPELINE)
    assert manager.data["total"] == 4 and column(manager, "lost")["count"] == 0


def test_board_filters_ignore_status(client_for, people, board):
    c = client_for(people["admin"])
    assert c.get(PIPELINE, {"city": "lahore"}).data["total"] == 3
    assert c.get(PIPELINE, {"tag": "vip"}).data["total"] == 1
    assert c.get(PIPELINE, {"company": board["mine_new"].company_id}).data["total"] == 1
    assert c.get(PIPELINE, {"assigned_to": people["staff"].pk}).data["total"] == 2
    assert c.get(PIPELINE, {"status": "won"}).data["total"] == 5  # a board always shows every column


def test_board_column_limit_keeps_true_count(client_for, people):
    for i in range(5):
        Contact.objects.create(first_name=f"N{i}", assigned_to=people["admin"])
    res = client_for(people["admin"]).get(PIPELINE, {"limit": 2})
    assert column(res, "new")["count"] == 5 and len(column(res, "new")["cards"]) == 2


def test_board_cards_most_recently_moved_first(client_for, people):
    old = Contact.objects.create(first_name="Old", assigned_to=people["admin"])
    Contact.objects.filter(pk=old.pk).update(status_changed_at=timezone.now() - timedelta(days=9))
    Contact.objects.create(first_name="Fresh", assigned_to=people["admin"])
    res = client_for(people["admin"]).get(PIPELINE)
    assert [c["full_name"] for c in column(res, "new")["cards"]] == ["Fresh", "Old"]


# ---------------------------------------------------------------- moving cards


def test_move_records_history_audit_and_timestamp(client_for, people, board):
    contact = board["mine_new"]
    before = contact.status_changed_at
    res = client_for(people["staff"]).patch(f"{CONTACTS}{contact.pk}/", {"status": "contacted"}, format="json")
    assert res.status_code == 200 and res.data["status"] == "contacted"
    contact.refresh_from_db()
    assert contact.status_changed_at > before
    change = ContactStatusChange.objects.get(contact=contact)
    assert (change.from_status, change.to_status, change.changed_by, change.reason) == ("new", "contacted", people["staff"], "")
    audit = AuditLog.objects.get(action="update", object_id=str(contact.pk))
    assert audit.changes == {"status": ["new", "contacted"]}  # internal timestamp not in the audit diff


def test_won_lost_reason_saved(client_for, people, board):
    pk = board["mine_new"].pk
    client_for(people["staff"]).patch(
        f"{CONTACTS}{pk}/", {"status": "lost", "status_reason": "  Chose a cheaper supplier  "}, format="json"
    )
    change = ContactStatusChange.objects.get(contact_id=pk)
    assert change.to_status == "lost" and change.reason == "Chose a cheaper supplier"


def test_reason_without_status_change_is_ignored(client_for, people, board):
    pk = board["mine_won"].pk
    before = Contact.objects.get(pk=pk).status_changed_at
    client_for(people["staff"]).patch(f"{CONTACTS}{pk}/", {"status": "won", "status_reason": "x", "city": "Multan"}, format="json")
    assert not ContactStatusChange.objects.filter(contact_id=pk).exists()
    assert Contact.objects.get(pk=pk).status_changed_at == before


def test_reason_length_limited(client_for, people, board):
    res = client_for(people["staff"]).patch(
        f"{CONTACTS}{board['mine_new'].pk}/", {"status": "won", "status_reason": "x" * 501}, format="json"
    )
    assert res.status_code == 400 and "status_reason" in res.data["errors"]


def test_create_records_initial_status(client_for, people):
    res = client_for(people["staff"]).post(CONTACTS, {"first_name": "Fresh", "status": "contacted"}, format="json")
    change = ContactStatusChange.objects.get(contact_id=res.data["id"])
    assert (change.from_status, change.to_status, change.changed_by) == ("", "contacted", people["staff"])
    assert res.data["status_changed_at"]


@pytest.mark.parametrize(
    "role,target,expected",
    [
        ("staff", "mine_new", 200),
        ("staff", "colleague", 404),  # can't see -> can't move
        ("manager", "colleague", 200),
        ("manager", "outsider", 404),
        ("admin", "outsider", 200),
    ],
)
def test_move_permissions_by_role(client_for, people, board, role, target, expected):
    res = client_for(people[role]).patch(f"{CONTACTS}{board[target].pk}/", {"status": "in_discussion"}, format="json")
    assert res.status_code == expected
    assert ContactStatusChange.objects.filter(contact=board[target]).exists() == (expected == 200)


def test_invalid_status_rejected(client_for, people, board):
    res = client_for(people["staff"]).patch(f"{CONTACTS}{board['mine_new'].pk}/", {"status": "archived"}, format="json")
    assert res.status_code == 400


# ---------------------------------------------------------------- history endpoint


def test_status_history_endpoint(client_for, people, board):
    c = client_for(people["staff"])
    pk = board["mine_new"].pk
    c.patch(f"{CONTACTS}{pk}/", {"status": "contacted"}, format="json")
    c.patch(f"{CONTACTS}{pk}/", {"status": "won", "status_reason": "Signed"}, format="json")
    res = c.get(f"{CONTACTS}{pk}/status-history/", HTTP_ACCEPT_LANGUAGE="ur")
    assert [(h["from_status"], h["to_status"]) for h in res.data] == [("contacted", "won"), ("new", "contacted")]
    assert res.data[0]["reason"] == "Signed" and res.data[0]["to_status_label"] == "کامیاب"
    assert res.data[0]["changed_by_name"] == people["staff"].full_name
    assert c.get(f"{CONTACTS}{board['colleague'].pk}/status-history/").status_code == 404


def test_history_is_deleted_with_contact(client_for, people, board):
    pk = board["mine_new"].pk
    client_for(people["staff"]).patch(f"{CONTACTS}{pk}/", {"status": "contacted"}, format="json")
    client_for(people["admin"]).delete(f"{CONTACTS}{pk}/")
    assert not ContactStatusChange.objects.filter(contact_id=pk).exists()


# ---------------------------------------------------------------- seeded history


def test_seed_builds_realistic_history():
    call_command("seed_demo", stdout=io.StringIO())
    call_command("seed_demo", stdout=io.StringIO())  # idempotent
    now = timezone.now()
    for contact in Contact.objects.all():
        history = list(contact.status_changes.order_by("changed_at"))
        assert history[0].from_status == "" and history[-1].to_status == contact.status
        assert all(a.to_status == b.from_status for a, b in zip(history, history[1:]))
        assert contact.status_changed_at == history[-1].changed_at
        assert timedelta(days=1) <= now - contact.status_changed_at <= timedelta(days=91)
    won_lost = ContactStatusChange.objects.filter(to_status__in=["won", "lost"])
    assert won_lost.exists() and won_lost.exclude(reason="").exists()
    assert len({c.status_changed_at.date() for c in Contact.objects.all()}) > 10  # spread out, not all "today"
