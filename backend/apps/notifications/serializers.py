from rest_framework import serializers

from .models import Notification, NotificationType
from .services import display_text


class NotificationSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.full_name", default=None, read_only=True)
    title = serializers.SerializerMethodField()
    body = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ["id", "type", "title", "body", "link", "is_read", "actor_name", "created_at"]
        read_only_fields = ["type", "link", "actor_name", "created_at"]

    def get_title(self, obj) -> str:
        return display_text(obj)[0]

    def get_body(self, obj) -> str:
        return display_text(obj)[1]


class PreferenceItemSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=NotificationType.choices)
    label = serializers.CharField(read_only=True)
    in_app = serializers.BooleanField()
    email = serializers.BooleanField()
