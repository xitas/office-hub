from rest_framework.routers import DefaultRouter

from .views import ErrandPhotoViewSet, ErrandViewSet

router = DefaultRouter()
router.register("errand-photos", ErrandPhotoViewSet, basename="errand-photo")
router.register("errands", ErrandViewSet, basename="errand")

urlpatterns = router.urls
