"""Role-based permission matrix shared by every module.

Each module maps actions to the roles allowed to perform them. Admins are
granted everything implicitly. Later phases add viewsets that point at an
existing module key; they never need new permission plumbing.
"""
from rest_framework.permissions import BasePermission

ADMIN = "admin"
MANAGER = "manager"
STAFF = "staff"
ROLES = (ADMIN, MANAGER, STAFF)

ALL = {ADMIN, MANAGER, STAFF}
MGMT = {ADMIN, MANAGER}
ADMIN_ONLY = {ADMIN}

PERMISSIONS: dict[str, dict[str, set[str]]] = {
    "dashboard": {"view": ALL},
    "users": {"view": ALL, "create": ADMIN_ONLY, "edit": ADMIN_ONLY, "delete": ADMIN_ONLY},
    "departments": {"view": ALL, "create": ADMIN_ONLY, "edit": ADMIN_ONLY, "delete": ADMIN_ONLY},
    "settings": {"view": ALL, "edit": ADMIN_ONLY},
    "audit": {"view": ADMIN_ONLY},
    # Phase 2
    "contacts": {
        "view": ALL, "create": ALL, "edit": ALL, "delete": MGMT, "import": MGMT, "export": MGMT, "assign_others": MGMT,
    },
    "tasks": {"view": ALL, "create": ALL, "edit": ALL, "delete": MGMT, "assign_others": MGMT},
    # Phase 3
    "chat": {"view": ALL, "create": ALL, "edit": ALL, "delete": ALL, "manage_channels": MGMT},
    "comms": {"view": ALL, "create": ALL, "edit": ALL, "delete": MGMT},
    "templates": {"view": ALL, "create": MGMT, "edit": MGMT, "delete": MGMT},
    "announcements": {"view": ALL, "create": MGMT, "edit": MGMT, "delete": MGMT},
    # Phase 4
    "bookings": {"view": ALL, "create": ALL, "edit": ALL, "delete": ALL},
    "resources": {"view": ALL, "create": ADMIN_ONLY, "edit": ADMIN_ONLY, "delete": ADMIN_ONLY},
    "calendar": {"view": ALL, "create": ALL, "edit": ALL, "delete": MGMT},
    "leave": {"view": ALL, "create": ALL, "edit": ALL, "delete": ALL, "approve": MGMT},
    "attendance": {"view": ALL, "create": ALL, "edit": MGMT},
    "inventory": {"view": ALL, "create": MGMT, "edit": MGMT, "delete": ADMIN_ONLY, "request": ALL, "approve": MGMT},
    "expenses": {"view": ALL, "create": ALL, "edit": ALL, "delete": ALL, "approve": MGMT},
    "planning": {"view": ALL, "create": MGMT, "edit": MGMT, "delete": MGMT},
    # Phase 5
    "visits": {"view": ALL, "create": ALL, "edit": ALL, "delete": MGMT, "view_map": MGMT},
    "vendors": {"view": ALL, "create": ALL, "edit": ALL, "delete": MGMT},
    "errands": {"view": ALL, "create": ALL, "edit": ALL, "delete": MGMT},
    # Phase 6
    "reports": {"view": MGMT, "export": MGMT},
}

METHOD_ACTIONS = {
    "GET": "view",
    "HEAD": "view",
    "OPTIONS": "view",
    "POST": "create",
    "PUT": "edit",
    "PATCH": "edit",
    "DELETE": "delete",
}


def has_perm(user, module: str, action: str) -> bool:
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.role == ADMIN or user.is_superuser:
        return True
    return user.role in PERMISSIONS.get(module, {}).get(action, set())


def permissions_for(user) -> list[str]:
    """Flat list of "module.action" strings the user holds (sent to the frontend)."""
    return sorted(
        f"{module}.{action}"
        for module, actions in PERMISSIONS.items()
        for action in actions
        if has_perm(user, module, action)
    )


class ModulePermission(BasePermission):
    """Checks the matrix using the viewset's `module` attribute.

    Custom viewset actions map to permission actions via `action_permissions`,
    e.g. ``action_permissions = {"approve": "approve"}``.
    """

    def has_permission(self, request, view):
        module = getattr(view, "module", None)
        if module is None:
            return bool(request.user and request.user.is_authenticated)
        action = getattr(view, "action_permissions", {}).get(getattr(view, "action", None))
        if action is None:
            action = METHOD_ACTIONS.get(request.method, "view")
        return has_perm(request.user, module, action)


def module_permission(module: str, action: str):
    """Permission class factory for plain APIViews, e.g. ``module_permission("settings", "edit")``."""

    class _Perm(BasePermission):
        def has_permission(self, request, view):
            return has_perm(request.user, module, action)

    _Perm.__name__ = f"Perm_{module}_{action}"
    return _Perm
