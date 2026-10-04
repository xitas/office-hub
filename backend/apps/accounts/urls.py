from rest_framework.routers import DefaultRouter

from .views import DepartmentViewSet, UserViewSet

router = DefaultRouter()
router.register("users", UserViewSet, basename="user")
router.register("departments", DepartmentViewSet, basename="department")

urlpatterns = router.urls
