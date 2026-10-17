from rest_framework.routers import DefaultRouter

from .views import VendorCategoryViewSet, VendorViewSet

router = DefaultRouter()
router.register("vendors/categories", VendorCategoryViewSet, basename="vendor-category")
router.register("vendors", VendorViewSet, basename="vendor")

urlpatterns = router.urls
