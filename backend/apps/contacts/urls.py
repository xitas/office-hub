from rest_framework.routers import DefaultRouter

from .transfer import ContactImportViewSet
from .views import CompanyViewSet, ContactViewSet, TagViewSet

router = DefaultRouter()
router.register("companies", CompanyViewSet, basename="company")
router.register("contacts", ContactViewSet, basename="contact")
router.register("tags", TagViewSet, basename="tag")
router.register("contact-imports", ContactImportViewSet, basename="contact-import")

urlpatterns = router.urls
