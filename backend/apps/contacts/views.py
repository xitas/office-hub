import django_filters
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.audit import AuditedViewSetMixin
from apps.core.permissions import ModulePermission
from apps.core.scoping import ScopedQuerysetMixin

from .models import Company
from .serializers import CompanySerializer


class CompanyFilter(django_filters.FilterSet):
    city = django_filters.CharFilter(field_name="city", lookup_expr="iexact")

    class Meta:
        model = Company
        fields = ["city", "industry", "assigned_to"]


class CompanyViewSet(AuditedViewSetMixin, ScopedQuerysetMixin, viewsets.ModelViewSet):
    """Companies. Staff see companies assigned to them, managers their department's, admins all."""

    module = "contacts"
    permission_classes = [ModulePermission]
    serializer_class = CompanySerializer
    queryset = Company.objects.select_related("assigned_to", "created_by", "updated_by")
    scope_owner_fields = ("assigned_to",)
    scope_department_field = "assigned_to__department"
    filterset_class = CompanyFilter
    search_fields = ["name", "email", "phone", "city"]
    ordering_fields = ["name", "city", "industry", "created_at", "updated_at"]
    action_permissions = {"facets": "view"}

    @extend_schema(responses={200: dict})
    @action(detail=False, methods=["get"])
    def facets(self, request):
        """Distinct values for the list filters, limited to the companies this user can see."""
        cities = self.get_queryset().exclude(city="").order_by("city").values_list("city", flat=True).distinct()
        # One entry per city regardless of capitalisation (the filter matches case-insensitively);
        # prefer the capitalised spelling ("Lahore" over "lahore").
        unique: dict[str, str] = {}
        for city in (c.strip() for c in cities):
            key = city.casefold()
            if key not in unique or (city[:1].isupper() and not unique[key][:1].isupper()):
                unique[key] = city
        return Response({"cities": sorted(unique.values(), key=str.casefold)})
