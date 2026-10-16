from datetime import timedelta

from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _
from django.utils.translation import gettext_noop as N_
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.core.audit import AuditedViewSetMixin, log_action
from apps.core.models import AuditLog
from apps.core.office_time import office_today
from apps.core.permissions import ModulePermission

from . import rules, services
from .models import WeeklyGoal
from .serializers import CarryOverSerializer, GoalUpdateSerializer, ProgressSerializer, WeeklyGoalSerializer


class WeeklyGoalViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    """Weekly goals. Managers plan their department's week, admins anyone's (and office-wide goals);
    owners, managers and admins record progress."""

    module = "planning"
    permission_classes = [ModulePermission]
    serializer_class = WeeklyGoalSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    # Owners (any role) record progress; who may is checked per goal.
    action_permissions = {"progress": "view", "history": "view", "carry_over": "create"}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return WeeklyGoal.objects.none()
        return rules.visible_goals(self.request.user).select_related("department", "owner")

    def _week(self):
        day = parse_date(self.request.query_params.get("week") or "") or office_today()
        return services.week_start_of(day)

    @extend_schema(operation_id="v1_planning_goals_list", parameters=[
        OpenApiParameter("week", str, description="Any day of the week (default: this week)"),
        OpenApiParameter("department", str, description="A department id, or 'office' for office-wide goals"),
    ], responses={200: dict})
    def list(self, request):
        """One week's goals, with the week's dates and its last working day."""
        week = self._week()
        qs = self.get_queryset().filter(week_start=week)
        dept = request.query_params.get("department")
        if dept == "office":
            qs = qs.filter(department__isnull=True)
        elif dept and dept.isdigit():
            qs = qs.filter(department_id=int(dept))
        goals = WeeklyGoalSerializer(qs.order_by("department__name", "position", "id"), many=True, context=self.get_serializer_context()).data
        last = services.last_working_day(week)
        return Response({
            "week_start": week, "week_end": week + timedelta(days=6), "last_working_day": last,
            "can_plan": rules.is_admin(request.user) or rules.is_manager(request.user),
            "goals": goals,
        })

    def perform_create(self, serializer):
        v = serializer.validated_data
        dept = v.get("department")
        if not rules.can_plan_for(self.request.user, dept.pk if dept else None):
            raise PermissionDenied(_("You can plan goals for your own department only."))
        week = services.week_start_of(v["week_start"])
        if week < services.week_start_of(office_today()):
            raise ValidationError({"week_start": [_("Plan this week or a later one.")]})
        try:
            services.check_owner(dept.pk if dept else None, v.get("owner"))
        except services.PlanningError as exc:
            raise ValidationError(exc.errors)
        serializer.validated_data["week_start"] = week
        super().perform_create(serializer)
        services.announce_owner(serializer.instance, self.request.user)

    def perform_update(self, serializer):
        goal = serializer.instance
        if not rules.can_manage(self.request.user, goal):
            raise PermissionDenied(_("You can't change this goal."))
        v = serializer.validated_data
        dept = v["department"].pk if v.get("department") else None if "department" in v else goal.department_id
        if dept != goal.department_id and not rules.can_plan_for(self.request.user, dept):
            raise PermissionDenied(_("You can plan goals for your own department only."))
        if "week_start" in v:
            v["week_start"] = services.week_start_of(v["week_start"])
        owner = v["owner"] if "owner" in v else goal.owner
        try:
            services.check_owner(dept, owner)
        except services.PlanningError as exc:
            raise ValidationError(exc.errors)
        old_owner = goal.owner_id
        super().perform_update(serializer)
        goal = serializer.instance
        if goal.done != bool(goal.completed_at):
            goal.completed_at = goal.updated_at if goal.done else None  # the target changed
            goal.save(update_fields=["completed_at"])
        if goal.owner_id != old_owner:
            services.announce_owner(goal, self.request.user)

    def perform_destroy(self, instance):
        if not rules.can_manage(self.request.user, instance):
            raise PermissionDenied(_("You can't delete this goal."))
        super().perform_destroy(instance)

    @extend_schema(request=ProgressSerializer, responses={200: WeeklyGoalSerializer})
    @action(detail=True, methods=["post"])
    def progress(self, request, pk=None):
        """Record progress: the new total (``value``) or a change (``add``)."""
        goal = self.get_object()
        data = ProgressSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            update = services.record(request.user, goal, **data.validated_data)
        except PermissionError:
            raise PermissionDenied(_("Only the goal's owner, its department's managers and admins record progress."))
        except services.PlanningError as exc:
            raise ValidationError(exc.errors)
        log_action(request.user, AuditLog.Action.UPDATE, goal, changes={"current": [update.before, update.after]},
                   description=N_("Progress updated"), request=request)
        return Response(WeeklyGoalSerializer(self.get_queryset().get(pk=goal.pk), context=self.get_serializer_context()).data)

    @extend_schema(responses={200: GoalUpdateSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        """The latest 50 progress updates."""
        return Response(GoalUpdateSerializer(self.get_object().updates.select_related("by")[:50], many=True).data)

    @extend_schema(request=CarryOverSerializer, responses={201: WeeklyGoalSerializer(many=True)})
    @action(detail=False, methods=["post"], url_path="carry-over")
    def carry_over(self, request):
        """Copy a week's unfinished goals to the next week (what's left of each target)."""
        data = CarryOverSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        week = services.week_start_of(v["week_start"])
        if v["all_departments"] and not rules.is_admin(request.user):
            raise PermissionDenied(_("Only admins copy every department's goals at once."))
        if not v["all_departments"] and not rules.can_plan_for(request.user, v["department"]):
            raise PermissionDenied(_("You can plan goals for your own department only."))
        copies = services.carry_over(request.user, week, v["department"], all_departments=v["all_departments"])
        for goal in copies:
            log_action(request.user, AuditLog.Action.CREATE, goal, changes={"carried_from": [None, goal.carried_from_id]},
                       description=N_("Goal carried over"), request=request)
        qs = self.get_queryset().filter(pk__in=[g.pk for g in copies])
        return Response(WeeklyGoalSerializer(qs, many=True, context=self.get_serializer_context()).data, status=status.HTTP_201_CREATED)
