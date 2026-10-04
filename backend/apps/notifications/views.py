from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notification, NotificationPreference, NotificationType
from .serializers import NotificationSerializer, PreferenceItemSerializer
from .services import get_preferences


class NotificationViewSet(mixins.ListModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """The signed-in user's own notifications."""

    serializer_class = NotificationSerializer
    filterset_fields = ["is_read", "type"]
    search_fields: list = []
    http_method_names = ["get", "patch", "post", "delete"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # schema generation
            return Notification.objects.none()
        return Notification.objects.filter(recipient=self.request.user).select_related("actor")

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        return Response({"count": self.get_queryset().filter(is_read=False).count()})

    @action(detail=True, methods=["post"], url_path="read")
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        notification.is_read = True
        notification.save(update_fields=["is_read"])
        return Response(self.get_serializer(notification).data)

    @action(detail=False, methods=["post"], url_path="read-all")
    def mark_all_read(self, request):
        updated = self.get_queryset().filter(is_read=False).update(is_read=True)
        return Response({"updated": updated})


class NotificationPreferencesView(APIView):
    @extend_schema(responses=PreferenceItemSerializer(many=True))
    def get(self, request):
        return Response(self._payload(request.user))

    @extend_schema(request=PreferenceItemSerializer(many=True), responses=PreferenceItemSerializer(many=True))
    def put(self, request):
        ser = PreferenceItemSerializer(data=request.data, many=True)
        ser.is_valid(raise_exception=True)
        for item in ser.validated_data:
            NotificationPreference.objects.update_or_create(
                user=request.user, type=item["type"], defaults={"in_app": item["in_app"], "email": item["email"]}
            )
        return Response(self._payload(request.user), status=status.HTTP_200_OK)

    def _payload(self, user):
        prefs = get_preferences(user)
        return [{"type": t.value, "label": t.label, **prefs[t.value]} for t in NotificationType]
