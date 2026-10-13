from rest_framework.routers import DefaultRouter

from .views import MessageTemplateViewSet

router = DefaultRouter()
router.register("templates", MessageTemplateViewSet, basename="template")

urlpatterns = router.urls
