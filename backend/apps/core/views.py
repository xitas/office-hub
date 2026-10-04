import django_filters
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from . import search as search_registry
from .audit import diff, log_action, snapshot
from .models import AuditLog, OrganizationSettings
from .permissions import METHOD_ACTIONS, ModulePermission, has_perm
from .serializers import AuditLogSerializer, OrganizationSettingsSerializer


class AuditLogFilter(django_filters.FilterSet):
    model = django_filters.CharFilter(field_name="content_type__model")
    date_from = django_filters.DateFilter(field_name="timestamp", lookup_expr="date__gte")
    date_to = django_filters.DateFilter(field_name="timestamp", lookup_expr="date__lte")

    class Meta:
        model = AuditLog
        fields = ["actor", "action", "model", "object_id", "date_from", "date_to"]


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    module = "audit"
    permission_classes = [ModulePermission]
    serializer_class = AuditLogSerializer
    queryset = AuditLog.objects.select_related("actor", "content_type")
    filterset_class = AuditLogFilter
    search_fields = ["object_repr", "description", "actor__full_name", "actor__email"]
    ordering_fields = ["timestamp"]


class OrganizationSettingsPermission(ModulePermission):
    def has_permission(self, request, view):
        return has_perm(request.user, "settings", "view" if METHOD_ACTIONS.get(request.method) == "view" else "edit")


class OrganizationSettingsView(generics.RetrieveUpdateAPIView):
    """Office-wide settings: everyone can read, admins can edit."""

    serializer_class = OrganizationSettingsSerializer
    permission_classes = [OrganizationSettingsPermission]

    def get_object(self):
        return OrganizationSettings.get_solo()

    def perform_update(self, serializer):
        before = snapshot(serializer.instance)
        instance = serializer.save()
        changes = diff(before, snapshot(instance))
        if changes:
            log_action(self.request.user, AuditLog.Action.UPDATE, instance, changes=changes, request=self.request)


class GlobalSearchView(APIView):
    @extend_schema(
        parameters=[
            OpenApiParameter("q", str, required=True),
            OpenApiParameter("types", str, description="Comma-separated source keys"),
        ],
        responses={200: dict},
    )
    def get(self, request):
        query = request.query_params.get("q", "")
        types = [t for t in request.query_params.get("types", "").split(",") if t] or None
        return Response({"query": query, "results": search_registry.search(request.user, query, types=types)})
