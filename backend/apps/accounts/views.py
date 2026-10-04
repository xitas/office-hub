from django.db.models import Count, Q
from django.utils.translation import gettext as _
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser

from apps.core.audit import AuditedViewSetMixin
from apps.core.permissions import ModulePermission
from apps.notifications.models import NotificationType
from apps.notifications.services import notify

from .models import Department, User
from .serializers import DepartmentSerializer, UserSerializer


class UserViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    """Staff directory for everyone; create/edit/delete for admins (see permission matrix)."""

    module = "users"
    permission_classes = [ModulePermission]
    serializer_class = UserSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    queryset = User.objects.select_related("department")
    filterset_fields = ["role", "department", "is_active"]
    search_fields = ["full_name", "email", "phone", "job_title"]
    ordering_fields = ["full_name", "email", "role", "date_joined", "last_login"]

    def get_queryset(self):
        qs = super().get_queryset()
        # Only admins see deactivated accounts.
        if not self.request.user.is_admin:
            qs = qs.filter(is_active=True)
        return qs

    def perform_update(self, serializer):
        before = {"role": serializer.instance.role, "department": serializer.instance.department}
        super().perform_update(serializer)
        user = serializer.instance
        params = {}
        if user.role != before["role"]:
            params["role"] = user.role
        if user.department != before["department"]:
            params["department"] = user.department.name if user.department else None
        if params:
            notify(
                user,
                NotificationType.SYSTEM,
                link="/settings",
                actor=self.request.user,
                message="account_updated",
                params={"actor": self.request.user.full_name, **params},
            )

    def perform_destroy(self, instance):
        if instance.pk == self.request.user.pk:
            raise ValidationError({"detail": _("You cannot delete your own account.")})
        super().perform_destroy(instance)


class DepartmentViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    module = "departments"
    permission_classes = [ModulePermission]
    serializer_class = DepartmentSerializer
    queryset = Department.objects.select_related("manager").annotate(
        member_count=Count("members", filter=Q(members__is_active=True))
    )
    search_fields = ["name", "description"]
    ordering_fields = ["name", "created_at"]
