from rest_framework.routers import DefaultRouter

from .views import AttachmentFileViewSet, ConversationViewSet, MessageViewSet

router = DefaultRouter()
router.register("chat/conversations", ConversationViewSet, basename="chat-conversation")
router.register("chat/messages", MessageViewSet, basename="chat-message")
router.register("chat/attachments", AttachmentFileViewSet, basename="chat-attachment")

urlpatterns = router.urls
