from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import AuditLogViewSet, GlobalSearchView, LivenessView, OrganizationSettingsView, SystemHealthView

router = DefaultRouter()
router.register("audit-log", AuditLogViewSet, basename="audit-log")

urlpatterns = [
    path("settings/organization/", OrganizationSettingsView.as_view(), name="org-settings"),
    path("search/", GlobalSearchView.as_view(), name="global-search"),
    path("health/", LivenessView.as_view(), name="health"),
    path("system/health/", SystemHealthView.as_view(), name="system-health"),
    *router.urls,
]
