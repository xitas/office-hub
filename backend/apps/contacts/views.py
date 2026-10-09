import django_filters
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.audit import AuditedViewSetMixin, snapshot
from apps.core.permissions import ModulePermission
from apps.core.scoping import ScopedQuerysetMixin

from .duplicates import find_duplicates
from .models import Company, Contact, Tag
from .serializers import CompanySerializer, ContactSerializer, TagSerializer
from .visibility import DEPARTMENT_FIELD, OWNER_FIELDS


def unique_cities(values) -> list[str]:
    """One entry per city regardless of capitalisation (filters match case-insensitively);
    prefer the capitalised spelling ("Lahore" over "lahore")."""
    unique: dict[str, str] = {}
    for city in (v.strip() for v in values):
        key = city.casefold()
        if key not in unique or (city[:1].isupper() and not unique[key][:1].isupper()):
            unique[key] = city
    return sorted(unique.values(), key=str.casefold)


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
    scope_owner_fields = OWNER_FIELDS
    scope_department_field = DEPARTMENT_FIELD
    filterset_class = CompanyFilter
    search_fields = ["name", "email", "phone", "city"]
    ordering_fields = ["name", "city", "industry", "created_at", "updated_at"]
    action_permissions = {"facets": "view"}

    @extend_schema(responses={200: dict})
    @action(detail=False, methods=["get"])
    def facets(self, request):
        """Distinct values for the list filters, limited to the companies this user can see."""
        cities = self.get_queryset().exclude(city="").values_list("city", flat=True)
        return Response({"cities": unique_cities(cities)})


class ContactFilter(django_filters.FilterSet):
    city = django_filters.CharFilter(field_name="city", lookup_expr="iexact")
    tag = django_filters.CharFilter(field_name="tags__name", lookup_expr="iexact")

    class Meta:
        model = Contact
        fields = ["company", "city", "tag", "status", "assigned_to"]


class ContactViewSet(AuditedViewSetMixin, ScopedQuerysetMixin, viewsets.ModelViewSet):
    """Contacts. Same visibility, assignment and delete rules as companies.

    Create/update responses include `duplicates`: other contacts sharing a phone/WhatsApp
    number or email. They're warnings only; saving is never blocked.
    """

    module = "contacts"
    permission_classes = [ModulePermission]
    serializer_class = ContactSerializer
    queryset = Contact.objects.select_related("company", "assigned_to", "created_by", "updated_by").prefetch_related("tags")
    scope_owner_fields = OWNER_FIELDS
    scope_department_field = DEPARTMENT_FIELD
    filterset_class = ContactFilter
    search_fields = ["first_name", "last_name", "phone", "whatsapp", "email", "phone_digits", "whatsapp_digits"]
    ordering_fields = ["first_name", "last_name", "status", "city", "created_at", "updated_at"]
    action_permissions = {"facets": "view", "duplicates": "view"}

    def audit_snapshot(self, instance) -> dict:
        data = snapshot(instance)
        for internal in ("phone_digits", "whatsapp_digits"):
            data.pop(internal, None)
        if instance.pk:
            data["tags"] = ", ".join(sorted(instance.tags.values_list("name", flat=True), key=str.casefold))
        return data

    def _with_duplicates(self, response, serializer):
        response.data["duplicates"] = serializer.duplicates(serializer.instance)
        return response

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        response = Response(self.get_serializer(serializer.instance).data, status=201)
        return self._with_duplicates(response, serializer)

    def update(self, request, *args, **kwargs):
        response = super().update(request, *args, **kwargs)
        instance = self.get_object()
        return self._with_duplicates(response, self.get_serializer(instance))

    @extend_schema(
        parameters=[
            OpenApiParameter("phone", str),
            OpenApiParameter("whatsapp", str),
            OpenApiParameter("email", str),
            OpenApiParameter("exclude", int, description="Contact id being edited"),
        ],
        responses={200: dict},
    )
    @action(detail=False, methods=["get"])
    def duplicates(self, request):
        """Live duplicate check while a form is being filled in (warning only)."""
        params = request.query_params
        exclude = params.get("exclude")
        return Response({
            "duplicates": find_duplicates(
                request.user,
                phone=params.get("phone", ""),
                whatsapp=params.get("whatsapp", ""),
                email=params.get("email", ""),
                exclude_id=int(exclude) if exclude and exclude.isdigit() else None,
            )
        })

    @extend_schema(responses={200: dict})
    @action(detail=False, methods=["get"])
    def facets(self, request):
        """Cities and tags used by the contacts this user can see (for list filters)."""
        qs = self.get_queryset()
        cities = qs.exclude(city="").values_list("city", flat=True)
        tags = Tag.objects.filter(contacts__in=qs).distinct().order_by("name").values_list("name", flat=True)
        return Response({"cities": unique_cities(cities), "tags": list(tags)})


class TagViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """All tags, for autocomplete. Tags are shared labels, so they aren't scoped per user."""

    module = "contacts"
    permission_classes = [ModulePermission]
    serializer_class = TagSerializer
    queryset = Tag.objects.all()
    search_fields = ["name"]
    pagination_class = None

    def filter_queryset(self, queryset):
        # Suggestions list: a handful of matches while typing, otherwise the most common tags.
        return super().filter_queryset(queryset)[: 20 if self.request.query_params.get("search") else 200]
