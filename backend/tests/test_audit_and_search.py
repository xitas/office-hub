import pytest

from apps.core.models import AuditLog

pytestmark = pytest.mark.django_db


def test_user_update_writes_diff_without_secrets(client_for, admin, staff):
    res = client_for(admin).patch(
        f"/api/v1/users/{staff.pk}/", {"job_title": "Team Lead", "password": "Brand!New#Pass1"}, format="json"
    )
    assert res.status_code == 200
    entry = AuditLog.objects.filter(action="update", object_id=str(staff.pk)).latest("timestamp")
    assert entry.actor == admin
    assert entry.changes["job_title"] == ["", "Team Lead"]
    assert entry.changes["password"] == ["***", "***"]
    assert "Brand!New#Pass1" not in str(entry.changes)


def test_create_and_delete_are_audited(client_for, admin):
    c = client_for(admin)
    res = c.post("/api/v1/departments/", {"name": "Marketing"}, format="json")
    assert res.status_code == 201
    created = AuditLog.objects.get(action="create", object_repr="Marketing")
    assert created.changes["name"] == "Marketing"
    assert created.ip == "127.0.0.1"
    assert c.delete(f"/api/v1/departments/{res.data['id']}/").status_code == 204
    assert AuditLog.objects.filter(action="delete", object_repr="Marketing").exists()


def test_audit_log_filters(client_for, admin, staff):
    client_for(admin).patch(f"/api/v1/users/{staff.pk}/", {"phone": "0300"}, format="json")
    res = client_for(admin).get("/api/v1/audit-log/", {"model": "user", "action": "update"})
    assert res.status_code == 200
    assert res.data["count"] == 1 and res.data["results"][0]["actor_name"] == admin.full_name


def test_global_search_finds_users_and_departments(client_for, staff, make_user):
    make_user("ali@test.com", full_name="Ali Hassan")
    res = client_for(staff).get("/api/v1/search/", {"q": "ali"})
    assert res.status_code == 200
    assert [u["title"] for u in res.data["results"]["users"]] == ["Ali Hassan"]

    res = client_for(staff).get("/api/v1/search/", {"q": "sal"})
    assert res.data["results"]["departments"][0]["title"] == "Sales"

    assert client_for(staff).get("/api/v1/search/", {"q": "a"}).data["results"] == {}


def test_department_search_link_depends_on_role(client_for, admin, manager, staff, departments):
    sales = departments["sales"]

    def link(user):
        hits = client_for(user).get("/api/v1/search/", {"q": "sales"}).data["results"]["departments"]
        return next(h["url"] for h in hits if h["id"] == sales.pk)

    assert link(admin) == "/admin/departments"
    assert link(manager) == f"/team?department={sales.pk}"
    assert link(staff) == f"/team?department={sales.pk}"


def test_dashboard_contract_and_scoping(client_for, admin, manager, staff, make_user):
    ops = make_user("ops@test.com", department="ops")
    client_for(admin).patch(f"/api/v1/users/{ops.pk}/", {"phone": "1"}, format="json")
    client_for(staff).patch("/api/v1/auth/me/", {"phone": "2"}, format="json")

    data = client_for(manager).get("/api/v1/dashboard/").data
    for key in ["tasks_today", "overdue", "meetings_today", "pending_approvals", "activity", "stats"]:
        assert key in data
    assert data["tasks_today"] is None  # module not built yet
    # Manager (sales) sees the sales staff's change, not the admin's.
    assert [a["actor_name"] for a in data["activity"]] == [staff.full_name]
    assert data["stats"]["departments"] is None

    admin_data = client_for(admin).get("/api/v1/dashboard/").data
    assert len(admin_data["activity"]) == 2
    assert admin_data["stats"]["departments"] == 2
    assert client_for(staff).get("/api/v1/dashboard/").data["stats"] is None


def test_foreign_key_changes_are_recorded_by_name(client_for, admin, staff, departments):
    client_for(admin).patch(f"/api/v1/users/{staff.pk}/", {"department": departments["ops"].pk}, format="json")
    entry = AuditLog.objects.filter(action="update", object_id=str(staff.pk)).latest("timestamp")
    assert entry.changes["department"] == ["Sales", "Operations"]
