from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .models import Notification
from .services import user_group


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    """Per-user event stream. Later phases (chat, tasks) push their own event types to the same group."""

    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=4401)
            return
        self.group = user_group(user.pk)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        await self.send_json({"type": "unread_count", "count": await self._unread_count(user)})

    async def disconnect(self, code):
        if hasattr(self, "group"):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def notification_new(self, event):
        await self.send_json({"type": "notification", "notification": event["notification"]})

    @database_sync_to_async
    def _unread_count(self, user):
        return Notification.objects.filter(recipient=user, is_read=False).count()
