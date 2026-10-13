from rest_framework.routers import DefaultRouter

from .views import AnnouncementFileViewSet, AnnouncementViewSet

router = DefaultRouter()
router.register("announcements", AnnouncementViewSet, basename="announcement")
router.register("announcement-files", AnnouncementFileViewSet, basename="announcement-file")

urlpatterns = router.urls
