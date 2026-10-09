from django.db.models import Q

from .permissions import ADMIN, MANAGER


def scope_for_user(queryset, user, owner_fields=("created_by",), department_field=None):
    """Limit rows by role: admin -> all, manager -> own department + own, staff -> own.

    Used by ScopedQuerysetMixin and anywhere else (search, duplicate checks) that must
    apply exactly the same visibility rules.
    """
    if user.role == ADMIN or user.is_superuser:
        return queryset
    visible = Q()
    for field in owner_fields:
        visible |= Q(**{field: user.pk})
    if user.role == MANAGER and department_field and user.department_id:
        visible |= Q(**{department_field: user.department_id})
    return queryset.filter(visible).distinct()


class ScopedQuerysetMixin:
    """Viewset mixin applying scope_for_user().

    Viewsets declare:
      scope_owner_fields: fields pointing at the owning/assigned user, e.g. ("assignees", "created_by")
      scope_department_field: path to the record's department id, e.g. "assignees__department"
    """

    scope_owner_fields: tuple[str, ...] = ("created_by",)
    scope_department_field: str | None = None

    def scope_queryset(self, queryset):
        return scope_for_user(queryset, self.request.user, self.scope_owner_fields, self.scope_department_field)

    def get_queryset(self):
        return self.scope_queryset(super().get_queryset())
