from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import BalancesView, LeaveRequestViewSet, LeaveTypeViewSet, TeamLeaveView

router = DefaultRouter()
router.register("leave/types", LeaveTypeViewSet, basename="leave-type")
router.register("leave/requests", LeaveRequestViewSet, basename="leave-request")

urlpatterns = [
    path("leave/balances/", BalancesView.as_view(), name="leave-balances"),
    path("leave/team/", TeamLeaveView.as_view(), name="leave-team"),
    *router.urls,
]
