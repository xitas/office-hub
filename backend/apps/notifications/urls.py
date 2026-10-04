from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import NotificationPreferencesView, NotificationViewSet

router = DefaultRouter()
router.register("", NotificationViewSet, basename="notification")

urlpatterns = [
    path("preferences/", NotificationPreferencesView.as_view(), name="notification-preferences"),
    *router.urls,
]
