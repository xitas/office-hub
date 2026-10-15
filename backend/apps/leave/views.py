from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.core.audit import AuditedViewSetMixin, log_action, snapshot
from apps.core.models import AuditLog
from apps.core.office_time import office_today
from apps.core.permissions import ModulePermission, module_permission

from . import rules, services
from .models import LeaveRequest, LeaveType
from .serializers import (
    AllowanceSerializer,
    LeaveDecisionSerializer,
    LeaveInputSerializer,
    LeaveRequestSerializer,
    LeaveTypeSerializer,
    TeamLeaveSerializer,
)


def days(value):
    """Days as text with one decimal ("3.0", "0.5"), the same everywhere in the API."""
    return None if value is None else f"{value:.1f}"


def balance_row(row) -> dict:
    return {**row, **{k: days(row[k]) for k in ("allowance", "used", "pending", "remaining")}}


class LeaveTypeViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    """Leave types. Everyone sees the active ones; admins manage them (a used type is made inactive, not deleted)."""

    module = "leave"
    permission_classes = [ModulePermission]
    serializer_class = LeaveTypeSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_permissions(self):
        if self.request.method not in ("GET", "HEAD", "OPTIONS"):
            return [module_permission("leave", "manage")()]
        return super().get_permissions()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return LeaveType.objects.none()
        qs = LeaveType.objects.all()
        return qs if rules.is_admin(self.request.user) else qs.filter(is_active=True)

    def perform_destroy(self, instance):
        if instance.requests.exists():
            raise ValidationError({"detail": _("This type has requests. Make it inactive instead.")})
        super().perform_destroy(instance)


@extend_schema_view(list=extend_schema(parameters=[
    OpenApiParameter("scope", str, enum=["mine", "team", "approvals"], description="mine (default); team: my department's (managers) or everyone's (admins); approvals: waiting for me"),
    OpenApiParameter("year", int),
    OpenApiParameter("status", str),
]))
class LeaveRequestViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    """Leave requests. Cancel instead of delete; managers and admins decide."""

    module = "leave"
    permission_classes = [ModulePermission]
    serializer_class = LeaveRequestSerializer
    pagination_class = None  # bounded: one person's year, or a team's year
    http_method_names = ["get", "post", "head", "options"]
    action_permissions = {"cancel": "edit", "decide": "approve", "preview": "view"}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return LeaveRequest.objects.none()
        user = self.request.user
        qs = rules.visible_requests(user).select_related("user__department", "leave_type", "decided_by")
        if self.action != "list":
            return qs
        params = self.request.query_params
        scope = params.get("scope", "mine")
        if scope == "approvals":
            return qs.filter(pk__in=rules.decidable_requests(user).values("pk")).order_by("start_date", "id")
        if scope == "team":
            qs = qs.filter(user__in=rules.team_users(user))
        else:
            qs = qs.filter(user=user)
        year = params.get("year")
        qs = qs.filter(start_date__year=int(year) if year and year.isdigit() else office_today().year)
        if s := params.get("status"):
            qs = qs.filter(status=s)
        return qs.order_by("-start_date", "-id")

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "today": office_today()}

    def _input(self):
        data = LeaveInputSerializer(data=self.request.data)
        data.is_valid(raise_exception=True)
        return data.validated_data

    @extend_schema(request=LeaveInputSerializer, responses={201: LeaveRequestSerializer})
    def create(self, request, *args, **kwargs):
        v = self._input()
        try:
            req = services.request_leave(request.user, v["leave_type"], v["start_date"], v["end_date"], v["half_day"], v["reason"])
        except services.LeaveError as exc:
            raise ValidationError(exc.errors)
        log_action(request.user, AuditLog.Action.CREATE, req, changes=snapshot(req), request=request)
        return Response(LeaveRequestSerializer(req, context=self.get_serializer_context()).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=LeaveInputSerializer, responses={200: dict})
    @action(detail=False, methods=["post"])
    def preview(self, request):
        """How many days a request would take (weekends and office holidays left out), and what's left after."""
        v = self._input()
        data = services.preview(request.user, v["leave_type"], v["start_date"], v["end_date"], v["half_day"])
        return Response({**data, "days": days(data["days"]), "remaining": days(data["remaining"]), "remaining_after": days(data["remaining_after"])})

    @extend_schema(request=None, responses={200: LeaveRequestSerializer})
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        req = self.get_object()
        old = req.status
        try:
            services.cancel(request.user, req)
        except PermissionError:
            raise PermissionDenied(_("This leave can't be cancelled."))
        log_action(request.user, AuditLog.Action.UPDATE, req, changes={"status": [old, req.status]}, request=request)
        return Response(LeaveRequestSerializer(req, context=self.get_serializer_context()).data)

    @extend_schema(request=LeaveDecisionSerializer, responses={200: LeaveRequestSerializer})
    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        req = self.get_object()
        data = LeaveDecisionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        old = req.status
        try:
            services.decide(request.user, req, approve=data.validated_data["approve"], note=data.validated_data["note"])
        except PermissionError:
            raise PermissionDenied(_("You can't decide on this request."))
        except services.LeaveError as exc:
            raise ValidationError(exc.errors)
        log_action(request.user, AuditLog.Action.UPDATE, req, changes={"status": [old, req.status]}, request=request)
        return Response(LeaveRequestSerializer(req, context=self.get_serializer_context()).data)


class BalancesView(APIView):
    """Leave balances for a year: mine, or my team's (managers) / everyone's (admins). Admins change allowances."""

    permission_classes = [module_permission("leave", "view")]

    @extend_schema(parameters=[OpenApiParameter("year", int), OpenApiParameter("scope", str, enum=["mine", "team"])], responses={200: dict})
    def get(self, request):
        year = int(request.query_params.get("year") or office_today().year)
        if request.query_params.get("scope") == "team":
            users = rules.team_users(request.user).filter(is_active=True).order_by("full_name")
        else:
            users = [request.user]
        rows = services.summaries(users, year)
        return Response([balance_row(r) for r in rows])

    @extend_schema(request=AllowanceSerializer, responses={200: dict})
    def patch(self, request):
        if not rules.is_admin(request.user):
            raise PermissionDenied(_("Only admins change leave allowances."))
        data = AllowanceSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        user = get_object_or_404(User, pk=v["user"])
        balance = services.balance_for(user, v["leave_type"], v["year"])
        before = {"allowance": str(balance.allowance), "note": balance.note}
        balance.allowance, balance.note = v["allowance"], v["note"]
        balance.save(update_fields=["allowance", "note", "updated_at"])
        changes = {k: [before[k], str(getattr(balance, k))] for k in before if before[k] != str(getattr(balance, k))}
        if changes:
            log_action(request.user, AuditLog.Action.UPDATE, balance, changes=changes, request=request)
        row = next(r for r in services.summaries([user], v["year"]) if r["leave_type"] == v["leave_type"].pk)
        return Response(balance_row(row))


class TeamLeaveView(APIView):
    """Who's off: approved leave of my department (admins: everyone) between two dates. No reasons."""

    permission_classes = [module_permission("leave", "view")]

    @extend_schema(parameters=[OpenApiParameter("from", str), OpenApiParameter("to", str)], responses={200: TeamLeaveSerializer(many=True)})
    def get(self, request):
        first = parse_date(request.query_params.get("from") or "") or office_today()
        last = parse_date(request.query_params.get("to") or "") or first
        if last < first or (last - first).days > 120:
            raise ValidationError({"from": [_("Give a date range (from, to) of at most %(n)s days.") % {"n": 120}]})
        qs = (
            rules.department_leave(request.user)
            .filter(start_date__lte=last, end_date__gte=first)
            .select_related("user", "leave_type")
            .order_by("start_date", "user__full_name")
        )
        return Response(TeamLeaveSerializer(qs, many=True).data)
