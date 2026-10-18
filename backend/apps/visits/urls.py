from rest_framework.routers import DefaultRouter

from .views import VisitPhotoViewSet, VisitViewSet

router = DefaultRouter()
router.register("visit-photos", VisitPhotoViewSet, basename="visit-photo")
router.register("visits", VisitViewSet, basename="visit")

urlpatterns = router.urls
