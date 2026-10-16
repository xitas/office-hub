import re
from datetime import date
from decimal import Decimal

from django.db.models import Count, Sum
from django.http import FileResponse, Http404
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.core.audit import log_action, snapshot
from apps.core.models import AuditLog, OrganizationSettings
from apps.core.office_time import office_today
from apps.core.permissions import ModulePermission

from . import rules, services
from .models import Expense, ExpenseReceipt
from .serializers import ExpenseDecisionSerializer, ExpenseInputSerializer, ExpenseSerializer, PaySerializer


def month_range(value: str | None) -> tuple[date, date]:
    """First and last day of "YYYY-MM" (this month when not given)."""
    if not value:
        today = office_today()
        year, month = today.year, today.month
    elif re.fullmatch(r"\d{4}-\d{2}", value) and 1 <= int(value[5:]) <= 12:
        year, month = int(value[:4]), int(value[5:])
    else:
        raise ValidationError({"month": [_("Use YYYY-MM.")]})
    first = date(year, month, 1)
    last = date(year + (month == 12), month % 12 + 1, 1)
    return first, date.fromordinal(last.toordinal() - 1)


@extend_schema_view(list=extend_schema(parameters=[
    OpenApiParameter("scope", str, enum=["mine", "team", "approvals", "to_pay"],
                     description="mine (default); team: my department's (managers) or everyone's (admins); approvals: waiting for my decision; to_pay: approved, not paid (admins)"),
    OpenApiParameter("month", str, description="YYYY-MM (mine and team; default this month)"),
    OpenApiParameter("status", str),
    OpenApiParameter("category", str),
    OpenApiParameter("user", int),
]))
class ExpenseViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Expense claims. Receipts are sent as multipart ``files``. Cancel instead of delete."""

    module = "expenses"
    permission_classes = [ModulePermission]
    serializer_class = ExpenseSerializer
    pagination_class = None  # bounded: a month, or what's waiting
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    http_method_names = ["get", "post", "patch", "head", "options"]
    action_permissions = {"cancel": "edit", "decide": "approve", "pay": "approve", "summary": "view"}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Expense.objects.none()
        user = self.request.user
        qs = rules.visible_expenses(user).select_related("user__department", "decided_by", "paid_by").prefetch_related("receipts")
        if self.action != "list":
            return qs
        params = self.request.query_params
        scope = params.get("scope", "mine")
        if scope == "approvals":
            return qs.filter(pk__in=rules.decidable_expenses(user).values("pk")).order_by("created_at", "id")
        if scope == "to_pay":
            return qs.filter(status=Expense.Status.APPROVED) if rules.is_admin(user) else qs.none()
        qs = self._scoped(qs, scope, params)
        for name in ("status", "category"):
            if value := params.get(name):
                qs = qs.filter(**{name: value})
        return qs.order_by("-spent_on", "-id")

    def _scoped(self, qs, scope, params):
        first, last = month_range(params.get("month"))
        qs = qs.filter(spent_on__range=(first, last))
        if scope == "team":
            qs = qs.filter(user__in=rules.team_users(self.request.user))
            if (u := params.get("user")) and u.isdigit():
                qs = qs.filter(user_id=int(u))
            return qs
        return qs.filter(user=self.request.user)

    def _out(self, expense):
        return ExpenseSerializer(self.get_queryset().get(pk=expense.pk), context=self.get_serializer_context()).data

    @extend_schema(request=ExpenseInputSerializer, responses={201: ExpenseSerializer})
    def create(self, request):
        data = ExpenseInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        v.pop("remove_receipts", None)
        try:
            expense = services.claim(request.user, files=request.FILES.getlist("files"), **v)
        except services.ExpenseError as exc:
            raise ValidationError(exc.errors)
        log_action(request.user, AuditLog.Action.CREATE, expense,
                   changes={**snapshot(expense), "receipts": [None, ", ".join(r.original_name for r in expense.receipts.all())]},
                   request=request)
        return Response(self._out(expense), status=status.HTTP_201_CREATED)

    @extend_schema(request=ExpenseInputSerializer, responses={200: ExpenseSerializer})
    def partial_update(self, request, pk=None):
        expense = self.get_object()
        data = ExpenseInputSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        v = dict(data.validated_data)
        remove = v.pop("remove_receipts", None) or []
        try:
            changes = services.update(request.user, expense, v, request.FILES.getlist("files"), remove)
        except PermissionError:
            raise PermissionDenied(_("Only a claim that's still waiting can be changed, by the person who made it."))
        except services.ExpenseError as exc:
            raise ValidationError(exc.errors)
        if changes:
            log_action(request.user, AuditLog.Action.UPDATE, expense, changes=changes, request=request)
        return Response(self._out(expense))

    def _status_change(self, request, expense, do, refusal):
        old = expense.status
        try:
            do()
        except PermissionError:
            raise PermissionDenied(refusal)
        log_action(request.user, AuditLog.Action.UPDATE, expense, changes={"status": [old, expense.status]}, request=request)
        return Response(self._out(expense))

    @extend_schema(request=ExpenseDecisionSerializer, responses={200: ExpenseSerializer})
    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        expense = self.get_object()
        data = ExpenseDecisionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        return self._status_change(request, expense, lambda: services.decide(request.user, expense, approve=v["approve"], note=v["note"]),
                                   _("You can't decide on this claim."))

    @extend_schema(request=None, responses={200: ExpenseSerializer})
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        expense = self.get_object()
        return self._status_change(request, expense, lambda: services.cancel(request.user, expense), _("This claim can't be cancelled."))

    @extend_schema(request=PaySerializer, responses={200: ExpenseSerializer})
    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        """Mark an approved claim paid (admins)."""
        expense = self.get_object()
        data = PaySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return self._status_change(request, expense, lambda: services.pay(request.user, expense, data.validated_data["note"]),
                                   _("Only admins mark approved claims paid."))

    @extend_schema(parameters=[OpenApiParameter("month", str), OpenApiParameter("scope", str, enum=["mine", "team"])],
                   responses={200: dict})
    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Totals for a month (by status, and approved or paid by category), in one query."""
        scope = "team" if request.query_params.get("scope") == "team" else "mine"
        qs = self._scoped(rules.visible_expenses(request.user), scope, request.query_params)
        rows = qs.order_by().values("status", "category").annotate(n=Count("id"), total=Sum("amount"))
        counts = {s: 0 for s in Expense.Status.values}
        amounts = {s: Decimal("0") for s in Expense.Status.values}
        by_category: dict[str, Decimal] = {}
        for r in rows:
            counts[r["status"]] += r["n"]
            amounts[r["status"]] += r["total"]
            if r["status"] in (Expense.Status.APPROVED, Expense.Status.PAID):
                by_category[r["category"]] = by_category.get(r["category"], Decimal("0")) + r["total"]
        first, _last = month_range(request.query_params.get("month"))
        return Response({
            "month": f"{first:%Y-%m}",
            "currency": OrganizationSettings.cached().currency,
            "by_status": {s: {"count": counts[s], "amount": f"{amounts[s]:.2f}"} for s in Expense.Status.values},
            "by_category": {c: f"{v:.2f}" for c, v in by_category.items()},
        })


class ReceiptFileViewSet(viewsets.GenericViewSet):
    """Download a receipt, or its image thumbnail. Only people who can see the claim."""

    module = "expenses"
    permission_classes = [ModulePermission]
    serializer_class = serializers.Serializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ExpenseReceipt.objects.none()
        return ExpenseReceipt.objects.filter(expense__in=rules.visible_expenses(self.request.user))

    def _serve(self, field, name, content_type, inline):
        if not field:
            raise Http404
        try:
            handle = field.open("rb")
        except FileNotFoundError:
            raise Http404
        response = FileResponse(handle, content_type=content_type, as_attachment=not inline, filename=name)
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        response["Cache-Control"] = "private, max-age=3600"
        return response

    @extend_schema(responses={(200, "application/octet-stream"): bytes})
    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        r = self.get_object()
        inline = r.kind in ("image", "pdf") and request.query_params.get("inline") == "1"
        return self._serve(r.file, r.original_name, r.content_type, inline)

    @extend_schema(responses={(200, "image/webp"): bytes})
    @action(detail=True, methods=["get"])
    def thumbnail(self, request, pk=None):
        return self._serve(self.get_object().thumbnail, "thumbnail.webp", "image/webp", True)
