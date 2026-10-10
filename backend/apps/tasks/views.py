from datetime import timedelta

import django_filters
from django.db.models import Case, F, Value, When
from django.utils import timezone
from django.utils.translation import gettext as _
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.filters import SearchFilter

from apps.core.audit import AuditedViewSetMixin, snapshot
from apps.core.permissions import ModulePermission

from .models import PRIORITY_RANK, Task, overdue_q
from .rules import can_delete, visible_tasks
from .serializers import TaskSerializer

DUE_CHOICES = ["today", "overdue", "upcoming", "none"]
UPCOMING_DAYS = 7


class MultiValueFilter(django_filters.BaseInFilter, django_filters.CharFilter):
    """`?status=todo,review` (comma-separated)."""


class TaskFilter(django_filters.FilterSet):
    mine = django_filters.BooleanFilter(method="filter_mine", label="Assigned to me")
    assigned_to = django_filters.NumberFilter(field_name="assignees")
    created_by = django_filters.NumberFilter(field_name="created_by")
    status = MultiValueFilter(field_name="status")
    priority = MultiValueFilter(field_name="priority")
    due_from = django_filters.DateFilter(field_name="due_date", lookup_expr="gte")
    due_to = django_filters.DateFilter(field_name="due_date", lookup_expr="lte")
    due = django_filters.ChoiceFilter(choices=[(c, c) for c in DUE_CHOICES], method="filter_due")
    overdue = django_filters.BooleanFilter(method="filter_overdue")
    contact = django_filters.NumberFilter(field_name="contact")
    company = django_filters.NumberFilter(field_name="company")

    class Meta:
        model = Task
        fields = ["mine", "assigned_to", "created_by", "status", "priority", "contact", "company"]

    def filter_mine(self, queryset, name, value):
        return queryset.filter(assignees=self.request.user) if value else queryset

    def filter_overdue(self, queryset, name, value):
        return queryset.filter(overdue_q()) if value else queryset.exclude(overdue_q())

    def filter_due(self, queryset, name, value):
        today = timezone.localdate()
        if value == "today":
            return queryset.filter(due_date=today)
        if value == "overdue":
            return queryset.filter(overdue_q())
        if value == "upcoming":
            return queryset.filter(due_date__gt=today, due_date__lte=today + timedelta(days=UPCOMING_DAYS))
        return queryset.filter(due_date__isnull=True)


# ?ordering= values. The default puts open tasks first, then by due date (no date last), most urgent first.
ORDERINGS = {
    "due": [F("due_date").asc(nulls_last=True), F("due_time").asc(nulls_last=True), "-priority_rank"],
    "-due": [F("due_date").desc(nulls_last=True), F("due_time").desc(nulls_last=True), "-priority_rank"],
    "priority": ["-priority_rank", F("due_date").asc(nulls_last=True)],
    "-priority": ["priority_rank", F("due_date").asc(nulls_last=True)],
    "created": ["created_at"],
    "-created": ["-created_at"],
    "-updated": ["-updated_at"],
}
DEFAULT_ORDERING = ["is_done", F("due_date").asc(nulls_last=True), F("due_time").asc(nulls_last=True), "-priority_rank", "-created_at"]


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter("ordering", str, enum=list(ORDERINGS), description="Default: open first, then by due date"),
            OpenApiParameter("search", str, description="Title"),
        ]
    )
)
class TaskViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    """Tasks. Staff see tasks they created or are assigned to, managers their department's, admins all.

    Assign: yourself and colleagues in your department (admins: anyone). Delete: managers and admins,
    or the task's creator. Moving a task to Done sets `completed_at`; reopening clears it.
    """

    module = "tasks"
    permission_classes = [ModulePermission]
    serializer_class = TaskSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_class = TaskFilter
    search_fields = ["title"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Task.objects.none()
        qs = visible_tasks(self.request.user).select_related(
            "contact", "company", "created_by", "updated_by"
        ).prefetch_related("assignees").annotate(
            priority_rank=PRIORITY_RANK,
            is_done=Case(When(status=Task.Status.DONE, then=Value(1)), default=Value(0)),
        )
        ordering = ORDERINGS.get(self.request.query_params.get("ordering", ""), DEFAULT_ORDERING)
        return qs.order_by(*ordering)

    def audit_snapshot(self, instance) -> dict:
        data = snapshot(instance)
        data.pop("updated_by", None)
        if instance.pk:
            data["assignees"] = ", ".join(sorted(u.full_name for u in instance.assignees.all()))
        return data

    def perform_destroy(self, instance):
        if not can_delete(self.request.user, instance):
            raise PermissionDenied(_("Only managers, admins or the person who created a task can delete it."))
        super().perform_destroy(instance)
