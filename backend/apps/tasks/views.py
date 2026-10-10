from datetime import date, timedelta

import django_filters
from django.db.models import Case, F, Value, When
from django.utils.translation import gettext as _
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.filters import SearchFilter

from apps.core.audit import AuditedViewSetMixin, snapshot
from apps.core.office_time import office_now, office_today
from apps.core.permissions import ModulePermission

from .models import PRIORITY_RANK, Task, overdue_q
from .rules import can_delete, visible_tasks
from .serializers import TaskSerializer

DUE_CHOICES = ["today", "overdue", "upcoming", "none"]
UPCOMING_DAYS = 7
BOARD_LIMIT = 100  # cards per column
DONE_WINDOW_DAYS = 14  # the board's Done column shows recently completed tasks only
CALENDAR_MAX_DAYS = 62  # a month view with its leading/trailing weeks fits easily
CALENDAR_LIMIT = 1000
UNDATED_LIMIT = 50


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
        today = office_today()
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

    def _filtered(self, ignore=()):
        """The list's queryset with its filters applied, minus the given query params."""
        request = self.request
        params = request.query_params.copy()
        for name in ignore:
            params.pop(name, None)
        qs = TaskFilter(params, queryset=self.get_queryset(), request=request).qs
        return SearchFilter().filter_queryset(request, qs, self)

    @extend_schema(responses={200: dict})
    @action(detail=False, methods=["get"])
    def board(self, request):
        """Kanban: one column per status with its count and cards. Accepts the list's filters (not `status`).

        Done shows tasks completed in the last 14 days (`count`); `total` counts every done task.
        Cards move by PATCH /tasks/{id}/ {"status"}, exactly like the status dropdown.
        """
        qs = self._filtered(ignore=["status"])
        since = office_now() - timedelta(days=DONE_WINDOW_DAYS)
        columns = []
        for status, label in Task.Status.choices:
            col = qs.filter(status=status)
            total = col.count()
            if status == Task.Status.DONE:
                col = col.filter(completed_at__gte=since).order_by("-completed_at", "-id")
            cards = list(col[:BOARD_LIMIT])
            columns.append({
                "status": status,
                "label": label,
                "count": col.count() if status == Task.Status.DONE else total,
                "total": total,
                "cards": self.get_serializer(cards, many=True).data,
            })
        return Response({"columns": columns, "done_since": since.date(), "done_window_days": DONE_WINDOW_DAYS})

    @extend_schema(
        parameters=[OpenApiParameter("start", str, required=True), OpenApiParameter("end", str, required=True)],
        responses={200: dict},
    )
    @action(detail=False, methods=["get"])
    def calendar(self, request):
        """Tasks due between `start` and `end` (office dates, inclusive) plus open tasks with no due date.

        Accepts the list's filters. Tasks move to another day by PATCH /tasks/{id}/ {"due_date"}.
        """
        try:
            start = date.fromisoformat(request.query_params.get("start", ""))
            end = date.fromisoformat(request.query_params.get("end", ""))
        except ValueError:
            raise ValidationError({"detail": _("Give start and end dates as YYYY-MM-DD.")})
        if end < start or (end - start).days > CALENDAR_MAX_DAYS:
            raise ValidationError({"detail": _("Choose a range of up to %(days)s days.") % {"days": CALENDAR_MAX_DAYS}})
        qs = self._filtered(ignore=["due_from", "due_to"])
        dated = qs.filter(due_date__gte=start, due_date__lte=end).order_by("due_date", F("due_time").asc(nulls_last=True), "-priority_rank")
        undated = qs.filter(due_date__isnull=True).exclude(status=Task.Status.DONE)
        return Response({
            "start": start,
            "end": end,
            "today": office_today(),
            "tasks": self.get_serializer(dated[:CALENDAR_LIMIT], many=True).data,
            "undated": self.get_serializer(undated[:UNDATED_LIMIT], many=True).data,
            "undated_count": undated.count(),
        })

    def perform_destroy(self, instance):
        if not can_delete(self.request.user, instance):
            raise PermissionDenied(_("Only managers, admins or the person who created a task can delete it."))
        super().perform_destroy(instance)
