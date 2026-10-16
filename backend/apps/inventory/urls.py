from rest_framework.routers import DefaultRouter

from .views import PurchaseRequestViewSet, SupplyItemViewSet

router = DefaultRouter()
router.register("inventory/items", SupplyItemViewSet, basename="supply-item")
router.register("inventory/requests", PurchaseRequestViewSet, basename="purchase-request")

urlpatterns = router.urls
