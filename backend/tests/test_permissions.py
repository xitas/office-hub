import pytest
from rest_framework.test import APIRequestFactory

from apps.accounts.models import User
from apps.core.permissions import PERMISSIONS, has_perm, permissions_for
from apps.core.scoping import ScopedQuerysetMixin

pytestmark = pytest.mark.django_db


def test_admin_has_everything(admin):
    assert all(has_perm(admin, m, a) for m, actions in PERMISSIONS.items() for a in actions)


def test_matrix_examples(manager, staff):
    assert has_perm(staff, "tasks", "create")
    assert not has_perm(staff, "tasks", "delete")
    assert has_perm(manager, "leave", "approve")
    assert not has_perm(staff, "leave", "approve")
    assert not has_perm(staff, "reports", "view")
    assert has_perm(manager, "reports", "view")
    assert not has_perm(manager, "audit", "view")
    assert not has_perm(manager, "nonexistent", "view")


def test_inactive_user_has_no_permissions(staff):
    staff.is_active = False
    assert permissions_for(staff) == []


@pytest.mark.parametrize(
    "role,expected",
    [("admin", 201), ("manager", 403), ("staff", 403)],
)
def test_only_admin_can_create_users(client_for, make_user, role, expected):
    user = make_user(f"{role}x@test.com", role)
    res = client_for(user).post(
        "/api/v1/users/",
        {"email": "new@test.com", "full_name": "New Person", "password": "Str0ng!Pass#2026", "role": "staff"},
        format="json",
    )
    assert res.status_code == expected


def test_everyone_can_list_directory_but_only_admin_sees_inactive(client_for, admin, staff, make_user):
    make_user("gone@test.com", is_active=False)
    staff_emails = {u["email"] for u in client_for(staff).get("/api/v1/users/").data["results"]}
    admin_emails = {u["email"] for u in client_for(admin).get("/api/v1/users/").data["results"]}
    assert "gone@test.com" not in staff_emails
    assert "gone@test.com" in admin_emails


def test_audit_log_is_admin_only(client_for, admin, manager, staff):
    assert client_for(admin).get("/api/v1/audit-log/").status_code == 200
    assert client_for(manager).get("/api/v1/audit-log/").status_code == 403
    assert client_for(staff).get("/api/v1/audit-log/").status_code == 403


def test_org_settings_read_all_edit_admin(client_for, admin, staff):
    assert client_for(staff).get("/api/v1/settings/organization/").data["currency"] == "PKR"
    assert client_for(staff).patch("/api/v1/settings/organization/", {"currency": "USD"}, format="json").status_code == 403
    res = client_for(admin).patch("/api/v1/settings/organization/", {"currency": "usd"}, format="json")
    assert res.status_code == 200 and res.data["currency"] == "USD"
    bad = client_for(admin).patch("/api/v1/settings/organization/", {"timezone": "Mars/Base"}, format="json")
    assert bad.status_code == 400 and "timezone" in bad.data["errors"]


def test_admin_cannot_demote_or_deactivate_self(client_for, admin):
    c = client_for(admin)
    assert c.patch(f"/api/v1/users/{admin.pk}/", {"role": "staff"}, format="json").status_code == 400
    assert c.patch(f"/api/v1/users/{admin.pk}/", {"is_active": False}, format="json").status_code == 400
    assert c.delete(f"/api/v1/users/{admin.pk}/").status_code == 400


def test_scoped_queryset_by_role(admin, manager, staff, make_user):
    other_dept = make_user("ops@test.com", department="ops")
    colleague = make_user("colleague@test.com", department="sales")

    class View(ScopedQuerysetMixin):
        scope_owner_fields = ("pk",)  # treat the user row itself as "own"
        scope_department_field = "department"

    def visible(user):
        view = View()
        view.request = APIRequestFactory().get("/")
        view.request.user = user
        return set(view.scope_queryset(User.objects.all()))

    assert visible(admin) == set(User.objects.all())
    assert visible(staff) == {staff}
    assert colleague in visible(manager) and staff in visible(manager)
    assert other_dept not in visible(manager)
