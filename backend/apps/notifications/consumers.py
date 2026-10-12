import time

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .models import Notification
from .services import user_group

TYPING_EVERY = 3  # seconds: at most one "typing" event per person per conversation
MEMBERSHIP_CACHE = 60  # seconds a membership check is trusted for typing/viewing


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    """Per-user event stream: notifications, and chat (messages, reactions, typing, presence).

    The client may send:
      {"type": "ping"}                                   keeps the connection (and presence) alive
      {"type": "chat.typing", "conversation": id}        "<name> is typing" for the other members
      {"type": "chat.viewing", "conversation": id|null}  which conversation this tab shows (no notifications for it)
    """

    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=4401)
            return
        self.user = user
        self.group = user_group(user.pk)
        self._typing_sent: dict[int, float] = {}
        self._members: dict[int, tuple[bool, float]] = {}
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        await self.send_json({"type": "unread_count", "count": await self._unread_count(user)})
        await self._presence(remove=False)

    async def disconnect(self, code):
        if hasattr(self, "group"):
            await self.channel_layer.group_discard(self.group, self.channel_name)
            await self._presence(remove=True)

    async def receive_json(self, content, **kwargs):
        kind = content.get("type")
        if kind == "ping":
            await self._presence(remove=False)
            await self.send_json({"type": "pong"})
        elif kind == "chat.typing":
            await self._typing(content.get("conversation"))
        elif kind == "chat.viewing":
            conversation = content.get("conversation")
            if conversation is not None and not await self._is_member(conversation):
                conversation = None
            await self._presence(remove=False, viewing=conversation)

    async def chat_event(self, event):
        # Chat messages, edits, reactions, typing, presence, read/unread changes (only members get them, see apps.chat.services).
        await self.send_json(event["data"])

    async def notification_new(self, event):
        await self.send_json({"type": "notification", "notification": event["notification"]})

    # ------------------------------------------------------------ chat helpers

    async def _is_member(self, conversation) -> bool:
        if not isinstance(conversation, int):
            return False
        cached = self._members.get(conversation)
        if cached and cached[1] > time.monotonic():
            return cached[0]
        member = await self._check_member(conversation)
        self._members[conversation] = (member, time.monotonic() + MEMBERSHIP_CACHE)
        return member

    async def _typing(self, conversation):
        now = time.monotonic()
        if not await self._is_member(conversation) or now - self._typing_sent.get(conversation, 0) < TYPING_EVERY:
            return
        self._typing_sent[conversation] = now
        recipients, data = await self._typing_event(conversation)
        for user_id in recipients:
            await self.channel_layer.group_send(user_group(user_id), {"type": "chat.event", "data": data})

    async def _presence(self, *, remove: bool, viewing=...):
        changed, recipients, data = await self._touch_presence(remove, viewing)
        if changed:
            for user_id in recipients:
                await self.channel_layer.group_send(user_group(user_id), {"type": "chat.event", "data": data})

    @database_sync_to_async
    def _touch_presence(self, remove, viewing):
        from apps.chat import presence, services

        before, after = presence.touch(self.user.pk, self.channel_name, viewing=viewing, remove=remove)
        if before == after:
            return False, (), None
        recipients, data = services.presence_event(self.user, after)
        return True, recipients, data

    @database_sync_to_async
    def _check_member(self, conversation):
        from apps.chat.models import Membership

        return Membership.objects.filter(conversation_id=conversation, user=self.user).exists()

    @database_sync_to_async
    def _typing_event(self, conversation):
        from apps.chat import services

        return services.typing_event(conversation, self.user)

    @database_sync_to_async
    def _unread_count(self, user):
        return Notification.objects.filter(recipient=user, is_read=False).count()
