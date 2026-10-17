from django.db.models import Count, F, Q
from django.utils.translation import gettext as _
from django.utils.translation import gettext_noop as N_
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.core.audit import AuditedViewSetMixin, log_action, snapshot
from apps.core.models import AuditLog
from apps.core.permissions import ModulePermission

from . import rules, services
from .models import PurchaseRequest, StockMovement, SupplyItem
from .serializers import (
    PurchaseDecisionSerializer,
    PurchaseInputSerializer,
    PurchaseRequestSerializer,
    ReceiveSerializer,
    StockChangeSerializer,
    StockMovementSerializer,
    SupplyItemSerializer,
)

OPEN = (PurchaseRequest.Status.PENDING, PurchaseRequest.Status.APPROVED)


@extend_schema_view(list=extend_schema(parameters=[
    OpenApiParameter("q", str, description="Name"),
    OpenApiParameter("category", str),
    OpenApiParameter("low", bool, description="Only items at or below their reorder level"),
    OpenApiParameter("supplier", int, description="Items usually bought from this vendor"),
    OpenApiParameter("inactive", bool, description="Include items no longer stocked (managers, admins)"),
]))
class SupplyItemViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    """Office supplies. Everyone sees the stock; managers and admins add items and record stock in and out."""

    module = "inventory"
    permission_classes = [ModulePermission]
    serializer_class = SupplyItemSerializer
    pagination_class = None  # an office's supplies: a bounded list
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    action_permissions = {"stock": "edit", "history": "view"}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return SupplyItem.objects.none()
        qs = SupplyItem.objects.select_related("supplier").annotate(
            open_requests=Count("purchase_requests", filter=Q(purchase_requests__status__in=OPEN))
        )
        params = self.request.query_params
        if not (rules.can_manage(self.request.user) and params.get("inactive") in ("1", "true")) and self.action == "list":
            qs = qs.filter(is_active=True)
        if self.action != "list":
            return qs
        if q := params.get("q", "").strip():
            qs = qs.filter(Q(name__icontains=q) | Q(name_ur__icontains=q))
        if c := params.get("category"):
            qs = qs.filter(category=c)
        if (s := params.get("supplier")) and s.isdigit():
            qs = qs.filter(supplier_id=int(s))
        if params.get("low") in ("1", "true"):
            qs = qs.filter(quantity__lte=F("reorder_level"))
        return qs.order_by("name")

    def perform_create(self, serializer):
        count = serializer.validated_data.pop("quantity", 0)
        item = serializer.save(created_by=self.request.user, quantity=0)
        if count:
            services.change_stock(self.request.user, item, StockMovement.Kind.ADJUSTED, count, _("Opening count"))
            item.refresh_from_db()
        log_action(self.request.user, AuditLog.Action.CREATE, item, changes=snapshot(item), request=self.request)

    def perform_destroy(self, instance):
        if instance.movements.exists() or instance.purchase_requests.exists():
            raise ValidationError({"detail": _("This item has a history. Mark it as no longer stocked instead.")})
        super().perform_destroy(instance)

    @extend_schema(request=StockChangeSerializer, responses={200: SupplyItemSerializer})
    @action(detail=True, methods=["post"])
    def stock(self, request, pk=None):
        """Record stock received, taken out, or a corrected count."""
        item = self.get_object()
        data = StockChangeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        before = item.quantity
        try:
            movement = services.change_stock(request.user, item, v["kind"], v["amount"], v["note"])
        except services.SupplyError as exc:
            raise ValidationError(exc.errors)
        log_action(request.user, AuditLog.Action.UPDATE, item, changes={"quantity": [before, movement.quantity_after]},
                   description=N_("Stock updated"), request=request)
        return Response(SupplyItemSerializer(self.get_queryset().get(pk=item.pk)).data)

    @extend_schema(responses={200: StockMovementSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        """The latest 50 stock changes."""
        item = self.get_object()
        return Response(StockMovementSerializer(item.movements.select_related("by")[:50], many=True).data)


@extend_schema_view(list=extend_schema(parameters=[
    OpenApiParameter("scope", str, enum=["mine", "all", "approvals", "to_receive"],
                     description="mine (default); all: everyone's (managers, admins); approvals: waiting for my decision; to_receive: approved, not received yet"),
    OpenApiParameter("status", str),
]))
class PurchaseRequestViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Requests to buy supplies. Anyone asks; managers approve their department's, admins anyone's."""

    module = "inventory"
    permission_classes = [ModulePermission]
    serializer_class = PurchaseRequestSerializer
    http_method_names = ["get", "post", "head", "options"]
    action_permissions = {"create": "request", "cancel": "request", "decide": "approve", "receive": "edit"}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return PurchaseRequest.objects.none()
        user = self.request.user
        qs = rules.visible_requests(user).select_related("requested_by__department", "item", "vendor", "decided_by", "received_by")
        if self.action != "list":
            return qs
        params = self.request.query_params
        scope = params.get("scope", "mine")
        if scope == "approvals":
            return qs.filter(pk__in=rules.decidable_requests(user).values("pk")).order_by("created_at", "id")
        if scope == "to_receive":
            return qs.filter(status=PurchaseRequest.Status.APPROVED).order_by("decided_at", "id")
        if scope != "all" or not rules.can_manage(user):
            qs = qs.filter(requested_by=user)
        if s := params.get("status"):
            qs = qs.filter(status=s)
        return qs.order_by("-created_at", "-id")

    @extend_schema(request=PurchaseInputSerializer, responses={201: PurchaseRequestSerializer})
    def create(self, request):
        data = PurchaseInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            req = services.request_purchase(request.user, **data.validated_data)
        except services.SupplyError as exc:
            raise ValidationError(exc.errors)
        log_action(request.user, AuditLog.Action.CREATE, req, changes=snapshot(req), request=request)
        return Response(self._out(req), status=status.HTTP_201_CREATED)

    def _out(self, req):
        return PurchaseRequestSerializer(self.get_queryset().get(pk=req.pk), context=self.get_serializer_context()).data

    @extend_schema(request=PurchaseDecisionSerializer, responses={200: PurchaseRequestSerializer})
    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        req = self.get_object()
        data = PurchaseDecisionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        old = req.status
        try:
            services.decide(request.user, req, approve=data.validated_data["approve"], note=data.validated_data["note"])
        except PermissionError:
            raise PermissionDenied(_("You can't decide on this request."))
        log_action(request.user, AuditLog.Action.UPDATE, req, changes={"status": [old, req.status]}, request=request)
        return Response(self._out(req))

    @extend_schema(request=None, responses={200: PurchaseRequestSerializer})
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        req = self.get_object()
        old = req.status
        try:
            services.cancel(request.user, req)
        except PermissionError:
            raise PermissionDenied(_("This request can't be cancelled."))
        log_action(request.user, AuditLog.Action.UPDATE, req, changes={"status": [old, req.status]}, request=request)
        return Response(self._out(req))

    @extend_schema(request=ReceiveSerializer, responses={200: PurchaseRequestSerializer})
    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        """Mark an approved request received (and add it to stock)."""
        req = self.get_object()
        data = ReceiveSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        old = req.status
        try:
            services.receive(request.user, req, **data.validated_data)
        except PermissionError:
            raise PermissionDenied(_("Only approved requests can be marked received."))
        except services.SupplyError as exc:
            raise ValidationError(exc.errors)
        req.refresh_from_db()
        log_action(request.user, AuditLog.Action.UPDATE, req, changes={"status": [old, req.status]}, request=request)
        return Response(self._out(req))
