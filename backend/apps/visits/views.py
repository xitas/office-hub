from datetime import datetime, time, timedelta

from django.db.models import BooleanField, Exists, ExpressionWrapper, OuterRef, Q
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.core.audit import log_action, snapshot
from apps.core.models import AuditLog
from apps.core.office_time import office_today, office_tz
from apps.core.permissions import ModulePermission

from . import rules, services
from .models import Visit
from .serializers import VisitCloseSerializer, VisitDecisionSerializer, VisitInputSerializer, VisitSerializer

MAX_RANGE_DAYS = 62


def day_start(day):
    return datetime.combine(day, time.min, tzinfo=office_tz())


def record_visible(user):
    """Whether the viewer may open the visit's contact or company (someone going on a colleague's client visit
    sees its name but not a link they can't open). Vendors are open to everyone; a place has no page."""
    from apps.contacts.visibility import visible_companies, visible_contacts

    return ExpressionWrapper(
        Exists(visible_contacts(user).filter(pk=OuterRef("contact_id"))) | Exists(visible_companies(user).filter(pk=OuterRef("company_id")))
        | Q(vendor__isnull=False),
        output_field=BooleanField(),
    )


@extend_schema_view(list=extend_schema(parameters=[
    OpenApiParameter("scope", str, enum=["mine", "team", "approvals", "today"],
                     description="mine (default): visits I go on or planned; team: my department's (managers) or everyone's (admins); approvals: waiting for my decision; today: today's visits I can see"),
    OpenApiParameter("when", str, enum=["upcoming", "past"], description="With mine (default upcoming)"),
    OpenApiParameter("from", str, description="With team: first day (YYYY-MM-DD)"),
    OpenApiParameter("to", str, description="With team: last day"),
    OpenApiParameter("person", int, description="With team: one person's visits"),
    OpenApiParameter("contact", int), OpenApiParameter("company", int), OpenApiParameter("vendor", int),
    OpenApiParameter("task", int, description="Visits carrying out this task"),
]))
class VisitViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Field visits. Anyone plans their own; managers plan their department's, admins anyone's. Cancel instead of delete."""

    module = "visits"
    permission_classes = [ModulePermission]
    serializer_class = VisitSerializer
    pagination_class = None  # bounded below: a date range, upcoming/past slices, or what's waiting
    http_method_names = ["get", "post", "patch", "head", "options"]
    action_permissions = {"decide": "edit", "close": "edit", "cancel": "edit", "people": "view"}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Visit.objects.none()
        user = self.request.user
        qs = rules.visible_visits(user).select_related(
            "contact", "company", "vendor", "assigned_to__department", "task", "decided_by", "closed_by", "created_by"
        ).prefetch_related("companions").annotate(record_visible=record_visible(user))
        if self.action != "list":
            return qs
        p = self.request.query_params
        for field in ("contact", "company", "vendor", "task"):
            if (v := p.get(field)) and v.isdigit():
                return qs.filter(**{f"{field}_id": int(v)}).order_by("-start")[:50]
        scope = p.get("scope", "mine")
        today = office_today()
        if scope == "approvals":
            return qs.filter(pk__in=rules.decidable_visits(user).values("pk")).order_by("start")
        if scope == "today":
            qs = qs.filter(start__gte=day_start(today), start__lt=day_start(today + timedelta(days=1))).exclude(
                status__in=[Visit.Status.CANCELLED, Visit.Status.REJECTED])
            if not (rules.is_admin(user) or rules.is_manager(user)):
                qs = qs.filter(pk__in=Visit.objects.filter(assigned_to=user).values("pk") | Visit.objects.filter(companions=user).values("pk"))
            return qs.order_by("start")
        if scope == "team":
            if not (rules.is_admin(user) or rules.is_manager(user)):
                raise PermissionDenied(_("Only managers and admins see the team's visits."))
            first = parse_date(p.get("from") or "") or today
            last = parse_date(p.get("to") or "") or first
            if last < first or (last - first).days > MAX_RANGE_DAYS:
                raise ValidationError({"from": [_("Give a date range (from, to) of at most %(n)s days.") % {"n": MAX_RANGE_DAYS}]})
            qs = qs.filter(start__gte=day_start(first), start__lt=day_start(last + timedelta(days=1)))
            if not rules.is_admin(user):
                qs = qs.filter(assigned_to__department_id=user.department_id)
            if (person := p.get("person")) and person.isdigit():
                qs = qs.filter(assigned_to_id=int(person))
            return qs.order_by("start")
        mine = Visit.objects.filter(assigned_to=user).values("pk") | Visit.objects.filter(companions=user).values("pk") \
            | Visit.objects.filter(created_by=user).values("pk")
        qs = qs.filter(pk__in=mine)
        if p.get("when") == "past":
            return qs.filter(start__lt=day_start(today)).order_by("-start")[:50]
        return qs.filter(start__gte=day_start(today)).order_by("start")[:100]

    def _out(self, visit):
        return VisitSerializer(self.get_queryset().get(pk=visit.pk), context=self.get_serializer_context()).data

    def _input(self, partial=False):
        data = VisitInputSerializer(data=self.request.data, partial=partial, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        return dict(data.validated_data)

    @extend_schema(request=VisitInputSerializer, responses={201: VisitSerializer})
    def create(self, request):
        v = self._input()
        v.setdefault("assigned_to", request.user)
        try:
            visit = services.plan(request.user, v)
        except services.VisitError as exc:
            raise ValidationError(exc.errors)
        log_action(request.user, AuditLog.Action.CREATE, visit,
                   changes={**snapshot(visit), "companions": ", ".join(u.full_name for u in visit.companions.all())}, request=request)
        return Response(self._out(visit), status=status.HTTP_201_CREATED)

    @extend_schema(request=VisitInputSerializer, responses={200: VisitSerializer})
    def partial_update(self, request, pk=None):
        visit = self.get_object()
        v = self._input(partial=True)
        try:
            changes = services.change(request.user, visit, v)
        except PermissionError:
            raise PermissionDenied(_("This visit can't be changed."))
        except services.VisitError as exc:
            raise ValidationError(exc.errors)
        if changes:
            log_action(request.user, AuditLog.Action.UPDATE, visit, changes=changes, request=request)
        return Response(self._out(visit))

    def _status(self, request, visit, do, refusal):
        old = visit.status
        try:
            do()
        except PermissionError:
            raise PermissionDenied(refusal)
        except services.VisitError as exc:
            raise ValidationError(exc.errors)
        log_action(request.user, AuditLog.Action.UPDATE, visit, changes={"status": [old, visit.status]}, request=request)
        return Response(self._out(visit))

    @extend_schema(request=VisitDecisionSerializer, responses={200: VisitSerializer})
    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        visit = self.get_object()
        data = VisitDecisionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        return self._status(request, visit, lambda: services.decide(request.user, visit, approve=v["approve"], note=v["note"]),
                            _("You can't decide on this visit."))

    @extend_schema(request=VisitCloseSerializer, responses={200: VisitSerializer})
    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        """Mark the visit done."""
        visit = self.get_object()
        data = VisitCloseSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return self._status(request, visit, lambda: services.close(request.user, visit, data.validated_data["note"]),
                            _("Only the people who went, their managers and admins mark a visit done."))

    @extend_schema(request=VisitCloseSerializer, responses={200: VisitSerializer})
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        visit = self.get_object()
        data = VisitCloseSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return self._status(request, visit, lambda: services.cancel(request.user, visit, data.validated_data["note"]),
                            _("This visit can't be cancelled."))

    @extend_schema(responses={200: dict})
    @action(detail=False, methods=["get"])
    def people(self, request):
        """Whom I may plan visits for, and whom I may take along (my department; admins: anyone)."""
        from apps.accounts.models import User

        user = request.user
        rows = lambda qs: [{"id": u.pk, "name": u.full_name, "department": u.department_id} for u in qs.order_by("full_name")]  # noqa: E731
        everyone = User.objects.filter(is_active=True)
        along = everyone if rules.is_admin(user) else everyone.filter(department_id=user.department_id) if user.department_id else everyone.none()
        return Response({"plan_for": rows(rules.planners_people(user)), "companions": rows(along)})
