from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import AttachmentFileViewSet, ConversationViewSet, MentionsView, MessageSearchView, MessageViewSet, RecordCardView

router = DefaultRouter()
router.register("chat/conversations", ConversationViewSet, basename="chat-conversation")
router.register("chat/messages", MessageViewSet, basename="chat-message")
router.register("chat/attachments", AttachmentFileViewSet, basename="chat-attachment")

urlpatterns = [
    path("chat/mentions/", MentionsView.as_view(), name="chat-mentions"),
    path("chat/search/", MessageSearchView.as_view(), name="chat-search"),
    path("chat/record-card/", RecordCardView.as_view(), name="chat-record-card"),
    *router.urls,
]
