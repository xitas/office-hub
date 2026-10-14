from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import CalendarView, EventViewSet

router = DefaultRouter()
router.register("events", EventViewSet, basename="event")

urlpatterns = [path("calendar/", CalendarView.as_view(), name="calendar"), *router.urls]
