from rest_framework.routers import DefaultRouter

from .views import ExpenseViewSet, ReceiptFileViewSet

router = DefaultRouter()
router.register("expenses/claims", ExpenseViewSet, basename="expense")
router.register("expenses/receipts", ReceiptFileViewSet, basename="expense-receipt")

urlpatterns = router.urls
