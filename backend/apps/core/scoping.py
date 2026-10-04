from django.db.models import Q

from .permissions import ADMIN, MANAGER


class ScopedQuerysetMixin:
    """Limit rows by role: admin -> all, manager -> own department + own, staff -> own.

    Viewsets declare:
      scope_owner_fields: fields pointing at the owning/assigned user, e.g. ("assignees", "created_by")
      scope_department_field: path to the record's department id, e.g. "assignees__department"
    """

    scope_owner_fields: tuple[str, ...] = ("created_by",)
    scope_department_field: str | None = None

    def scope_queryset(self, queryset):
        user = self.request.user
        if user.role == ADMIN or user.is_superuser:
            return queryset
        visible = Q()
        for field in self.scope_owner_fields:
            visible |= Q(**{field: user.pk})
        if user.role == MANAGER and self.scope_department_field and user.department_id:
            visible |= Q(**{self.scope_department_field: user.department_id})
        return queryset.filter(visible).distinct()

    def get_queryset(self):
        return self.scope_queryset(super().get_queryset())
