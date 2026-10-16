from rest_framework.routers import DefaultRouter

from .views import WeeklyGoalViewSet

router = DefaultRouter()
router.register("planning/goals", WeeklyGoalViewSet, basename="weekly-goal")

urlpatterns = router.urls
