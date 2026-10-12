"""Chat operations shared by the API, signals, the seed command and tests.

Live events go to each member's own WebSocket group (the same per-user stream as notifications),
so only current members ever receive a conversation's messages. They are sent after the
transaction commits, through the Redis channel layer whenever REDIS_URL is set.
"""
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, IntegerField, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.accounts.models import Department, User
from apps.notifications.services import push

from .models import Conversation, Membership, Message

EDIT_WINDOW = timedelta(minutes=15)
PREVIEW_LENGTH = 120
GENERAL_NAME = "General"


# ================================================================ unread counts


def unread_count_expr(conversation_ref="conversation", user_ref="user", last_read_ref="last_read_id"):
    """Unread messages for a membership row: newer than its read position, by others, not deleted."""
    unread = (
        Message.objects.filter(conversation=OuterRef(conversation_ref), id__gt=OuterRef(last_read_ref), deleted_at__isnull=True)
        .exclude(author_id=OuterRef(user_ref))
        .order_by()
        .values("conversation")
        .annotate(n=Count("pk"))
        .values("n")
    )
    return Coalesce(Subquery(unread, output_field=IntegerField()), 0)


def unread_by_member(conversation) -> dict[int, int]:
    """{user_id: unread count} for every member, in one query."""
    rows = Membership.objects.filter(conversation=conversation).annotate(unread=unread_count_expr())
    return dict(rows.values_list("user_id", "unread"))


def total_unread(user) -> int:
    rows = Membership.objects.filter(user=user, conversation__archived_at__isnull=True).annotate(unread=unread_count_expr())
    return sum(rows.values_list("unread", flat=True))


# ================================================================ serialization (API and WebSocket)


def person(user) -> dict | None:
    if user is None:
        return None
    return {"id": user.pk, "full_name": user.full_name, "avatar": user.avatar.url if user.avatar else None}


def message_data(message) -> dict:
    deleted = message.is_deleted
    return {
        "id": message.pk,
        "conversation": message.conversation_id,
        "author": person(message.author),
        "body": "" if deleted else message.body,
        "reply_to": message.reply_to_id,
        "created_at": message.created_at.isoformat(),
        "edited_at": message.edited_at.isoformat() if message.edited_at else None,
        "deleted": deleted,
        "editable_until": None if deleted else (message.created_at + EDIT_WINDOW).isoformat(),
    }


def preview_data(message) -> dict | None:
    if message is None:
        return None
    deleted = message.is_deleted
    return {
        "id": message.pk,
        "author": person(message.author),
        "body": "" if deleted else message.body[:PREVIEW_LENGTH],
        "deleted": deleted,
        "created_at": message.created_at.isoformat(),
    }


# ================================================================ live events


def _send(user_ids, data: dict):
    def deliver():
        for user_id in user_ids:
            push(user_id, {"type": "chat.event", "data": data})

    transaction.on_commit(deliver)


def broadcast_message(message, event: str):
    """message.new / message.updated to every member, each with their own unread count."""
    unread = unread_by_member(message.conversation)
    payload = message_data(message)

    def deliver():
        for user_id, count in unread.items():
            push(user_id, {"type": "chat.event", "data": {
                "type": "chat", "event": event, "conversation": message.conversation_id, "message": payload, "unread": count,
            }})

    transaction.on_commit(deliver)


def notify_conversations_changed(user_ids, conversation_id):
    """Someone joined, left or was added/removed, or a channel changed: lists should refresh."""
    _send(list(user_ids), {"type": "chat", "event": "conversation.changed", "conversation": conversation_id})


# ================================================================ messages


def send_message(conversation, author, body: str, reply_to=None) -> Message:
    with transaction.atomic():
        message = Message.objects.create(conversation=conversation, author=author, body=body, reply_to=reply_to)
        Conversation.objects.filter(pk=conversation.pk).update(last_message_at=message.created_at)
        # Your own message is read by you.
        Membership.objects.filter(conversation=conversation, user=author).update(last_read_id=message.pk)
        broadcast_message(message, "message.new")
    return message


def edit_message(message, body: str) -> Message:
    message.body = body
    message.edited_at = timezone.now()
    message.save(update_fields=["body", "edited_at"])
    broadcast_message(message, "message.updated")
    return message


def delete_message(message) -> Message:
    message.body = ""
    message.deleted_at = timezone.now()
    message.save(update_fields=["body", "deleted_at"])
    broadcast_message(message, "message.updated")
    return message


def mark_read(conversation, user, up_to: int | None = None) -> int:
    """Move the user's read position forward (never back). Returns their unread count afterwards."""
    newest = Message.objects.filter(conversation=conversation).order_by("-id").values_list("pk", flat=True).first() or 0
    target = newest if up_to is None else min(up_to, newest)
    Membership.objects.filter(conversation=conversation, user=user, last_read_id__lt=target).update(last_read_id=target)
    count = unread_by_member(conversation).get(user.pk, 0)
    # The user's other tabs and devices clear their badge too.
    _send([user.pk], {"type": "chat", "event": "read", "conversation": conversation.pk, "unread": count})
    return count


# ================================================================ direct messages


def dm_key(a, b) -> str:
    low, high = sorted([a.pk, b.pk])
    return f"{low}:{high}"


def get_or_create_dm(user, other) -> tuple[Conversation, bool]:
    key = dm_key(user, other)
    conversation = Conversation.objects.filter(dm_key=key).first()
    if conversation:
        return conversation, False
    with transaction.atomic():
        conversation, created = Conversation.objects.get_or_create(
            dm_key=key, defaults={"kind": Conversation.Kind.DIRECT, "is_private": True, "created_by": user}
        )
        if created:
            Membership.objects.bulk_create([Membership(conversation=conversation, user=u) for u in {user, other}])
    return conversation, created


# ================================================================ default channels (automatic membership)


def general_channel() -> Conversation:
    channel = Conversation.objects.filter(is_default=True, channel_type=Conversation.ChannelType.GENERAL).first()
    if channel is None:
        channel = Conversation.objects.create(
            name=GENERAL_NAME, description="Everyone in the office", channel_type=Conversation.ChannelType.GENERAL,
            is_default=True,
        )
        add_members(channel, User.objects.filter(is_active=True))
    return channel


def department_channel(department) -> Conversation:
    channel = Conversation.objects.filter(
        is_default=True, channel_type=Conversation.ChannelType.DEPARTMENT, department=department
    ).first()
    if channel is None:
        channel = Conversation.objects.create(
            name=department.name[:80], channel_type=Conversation.ChannelType.DEPARTMENT, department=department,
            is_default=True, is_private=True,
        )
        add_members(channel, User.objects.filter(is_active=True, department=department))
    elif channel.name != department.name[:80] or channel.archived:
        channel.name = department.name[:80]
        channel.archived_at = None
        channel.save(update_fields=["name", "archived_at", "updated_at"])
    return channel


def add_members(conversation, users) -> list[int]:
    existing = set(Membership.objects.filter(conversation=conversation).values_list("user_id", flat=True))
    # New members start "caught up": earlier history is there to read, but not counted as unread.
    newest = Message.objects.filter(conversation=conversation).order_by("-id").values_list("pk", flat=True).first() or 0
    new = [Membership(conversation=conversation, user=u, last_read_id=newest) for u in users if u.pk not in existing]
    Membership.objects.bulk_create(new, ignore_conflicts=True)
    added = [m.user_id for m in new]
    if added:
        notify_conversations_changed(added, conversation.pk)
    return added


def remove_members(conversation, user_ids) -> list[int]:
    gone = list(Membership.objects.filter(conversation=conversation, user_id__in=user_ids).values_list("user_id", flat=True))
    Membership.objects.filter(conversation=conversation, user_id__in=gone).delete()
    if gone:
        notify_conversations_changed(gone, conversation.pk)
    return gone


def sync_default_memberships(user):
    """General for every active user, plus their department's channel; nothing for inactive users."""
    defaults = Conversation.objects.filter(is_default=True)
    wanted = set()
    if user.is_active:
        wanted.add(general_channel().pk)
        if user.department_id:
            wanted.add(department_channel(user.department).pk)
    current = set(Membership.objects.filter(user=user, conversation__in=defaults).values_list("conversation_id", flat=True))
    for conversation in Conversation.objects.filter(pk__in=wanted - current):
        add_members(conversation, [user])
    for conversation_id in current - wanted:
        remove_members(Conversation(pk=conversation_id), [user.pk])


def ensure_default_channels():
    """General plus one channel per department, with everyone in the right ones (idempotent)."""
    general_channel()
    for department in Department.objects.all():
        department_channel(department)
    for user in User.objects.all():
        sync_default_memberships(user)
