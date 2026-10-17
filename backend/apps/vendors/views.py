from django.db.models import Count, Q, Sum
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.core.audit import AuditedViewSetMixin, snapshot
from apps.core.models import OrganizationSettings
from apps.core.office_time import office_today
from apps.core.permissions import ModulePermission, has_perm, module_permission
from apps.core.phones import phone_query_variants

from . import rules, services
from .models import Vendor, VendorCategory
from .serializers import VendorCategorySerializer, VendorSerializer


@extend_schema_view(list=extend_schema(parameters=[
    OpenApiParameter("q", str, description="Name, contact person, phone (any format), city, areas or notes"),
    OpenApiParameter("category", int),
    OpenApiParameter("city", str),
    OpenApiParameter("preferred", bool),
    OpenApiParameter("inactive", bool, description="Include vendors no longer used (managers, admins)"),
]))
class VendorViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    """The office's vendors and suppliers. Everyone adds and corrects them; managers and admins mark them
    preferred or inactive and delete unused ones."""

    module = "vendors"
    permission_classes = [ModulePermission]
    serializer_class = VendorSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    action_permissions = {"activity": "view", "cities": "view"}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Vendor.objects.none()
        qs = Vendor.objects.select_related("created_by").prefetch_related("categories")
        params = self.request.query_params
        if self.action != "list":
            return qs
        if not (rules.can_curate(self.request.user) and params.get("inactive") in ("1", "true")):
            qs = qs.filter(is_active=True)
        if q := params.get("q", "").strip():
            match = Q()
            for field in ("name", "contact_person", "city", "areas", "notes", "email"):
                match |= Q(**{f"{field}__icontains": q})
            for number in phone_query_variants(q):
                match |= Q(phone_digits__contains=number) | Q(whatsapp_digits__contains=number)
            qs = qs.filter(match)
        if (c := params.get("category")) and c.isdigit():
            qs = qs.filter(categories=int(c))
        if city := params.get("city", "").strip():
            qs = qs.filter(city__iexact=city)
        if params.get("preferred") in ("1", "true"):
            qs = qs.filter(preferred=True)
        return qs.order_by("-preferred", "name")

    def audit_snapshot(self, instance) -> dict:
        return {**snapshot(instance), "categories": sorted(c.name for c in instance.categories.all())}

    def perform_create(self, serializer):
        super().perform_create(serializer)
        services.announce_new(serializer.instance, self.request.user)

    def perform_destroy(self, instance):
        linked = instance.supplies.exists() or instance.purchase_requests.exists() or instance.expenses.exists() \
            or instance.timeline_entries.exists()
        if linked:
            raise ValidationError({"detail": _("This vendor is used in supplies, requests, expenses or the timeline. Mark it inactive instead.")})
        super().perform_destroy(instance)

    @extend_schema(responses={200: dict})
    @action(detail=True, methods=["get"])
    def activity(self, request, pk=None):
        """What the office does with this vendor: its supplies, recent purchase requests and expense claims
        (only the requests and claims you may see), in a fixed number of queries."""
        vendor = self.get_object()
        user = request.user
        supplies = [
            {"id": i.pk, "name": i.name, "name_ur": i.name_ur, "quantity": i.quantity, "unit": i.unit, "is_low": i.is_low}
            for i in vendor.supplies.filter(is_active=True).order_by("name")
        ]
        out = {"supplies": supplies, "purchases": None, "expenses": None}
        if has_perm(user, "inventory", "view"):
            from apps.inventory import rules as inventory_rules

            requests = inventory_rules.visible_requests(user).filter(vendor=vendor).select_related("requested_by", "item")
            out["purchases"] = [
                {"id": r.pk, "item_name": r.item_name, "item_name_ur": r.item.name_ur if r.item else "", "quantity": r.quantity,
                 "unit": r.unit, "status": r.status, "requested_by_name": r.requested_by.full_name, "created_at": r.created_at}
                for r in requests.order_by("-created_at")[:10]
            ]
        if has_perm(user, "expenses", "view"):
            from apps.expenses import rules as expense_rules
            from apps.expenses.models import Expense

            claims = expense_rules.visible_expenses(user).filter(vendor=vendor)
            year = claims.filter(spent_on__year=office_today().year, status__in=[Expense.Status.APPROVED, Expense.Status.PAID])
            totals = year.aggregate(n=Count("id"), total=Sum("amount"))
            out["expenses"] = {
                "currency": OrganizationSettings.cached().currency,
                "year_count": totals["n"], "year_total": f"{totals['total'] or 0:.2f}",
                "recent": [
                    {"id": e.pk, "title": e.title, "amount": f"{e.amount:.2f}", "currency": e.currency, "spent_on": e.spent_on,
                     "status": e.status, "user_name": e.user.full_name}
                    for e in claims.select_related("user").order_by("-spent_on", "-id")[:5]
                ],
            }
        return Response(out)

    @extend_schema(responses={200: list[str]})
    @action(detail=False, methods=["get"])
    def cities(self, request):
        """Cities of active vendors, for the filter."""
        cities = Vendor.objects.filter(is_active=True).exclude(city="").values_list("city", flat=True).distinct().order_by("city")
        return Response(list(cities))


class VendorCategoryViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    """Service categories. Everyone sees the active ones; admins manage them (a used category is made inactive)."""

    module = "vendors"
    permission_classes = [ModulePermission]
    serializer_class = VendorCategorySerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_permissions(self):
        if self.request.method not in ("GET", "HEAD", "OPTIONS"):
            return [module_permission("vendors", "manage")()]
        return super().get_permissions()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return VendorCategory.objects.none()
        qs = VendorCategory.objects.annotate(vendor_count=Count("vendors", filter=Q(vendors__is_active=True)))
        qs = qs.order_by("position", "name")  # (grouped queries ignore Meta.ordering)
        return qs if rules.can_manage_categories(self.request.user) else qs.filter(is_active=True)

    def perform_destroy(self, instance):
        if instance.vendors.exists():
            raise PermissionDenied(_("Vendors use this category. Make it inactive instead."))
        super().perform_destroy(instance)
