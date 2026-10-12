"""Chat operations shared by the API, the WebSocket consumer, signals, jobs, the seed command and tests.

Live events go to each member's own WebSocket group (the same per-user stream as notifications),
so only current members ever receive a conversation's messages, reactions or typing. They are
sent after the transaction commits, through the Redis channel layer whenever REDIS_URL is set.
"""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Exists, IntegerField, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from rest_framework.exceptions import ValidationError

from apps.accounts.models import Department, User
from apps.core.email import queue_email
from apps.notifications.models import Notification, NotificationType
from apps.notifications.services import get_preferences, notify, push
from apps.tasks.files import FileRejected, check_upload, make_thumbnail

from . import presence
from .models import REACTIONS, Conversation, Membership, Message, MessageAttachment, Reaction

EDIT_WINDOW = timedelta(minutes=15)
PREVIEW_LENGTH = 120
GENERAL_NAME = "General"
MAX_FILES_PER_MESSAGE = 5
DM_EMAIL_DELAY = timedelta(minutes=30)  # a direct message unread this long is emailed
DM_EMAIL_LOOKBACK = timedelta(hours=24)  # after downtime, never email about older messages


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
    """For the badge: muted and archived conversations don't count."""
    rows = Membership.objects.filter(user=user, muted=False, conversation__archived_at__isnull=True).annotate(
        unread=unread_count_expr()
    )
    return sum(rows.values_list("unread", flat=True))


# ================================================================ serialization (API and WebSocket)


def person(user) -> dict | None:
    if user is None:
        return None
    return {"id": user.pk, "full_name": user.full_name, "avatar": user.avatar.url if user.avatar else None}


def with_details(queryset):
    """Everything message_data() reads, in a fixed number of queries."""
    return queryset.select_related("author", "reply_to__author").prefetch_related("reactions__user", "attachments")


def attachment_data(a) -> dict:
    return {
        "id": a.pk,
        "original_name": a.original_name,
        "size": a.size,
        "content_type": a.content_type,
        "kind": a.kind,
        # Relative API paths: the frontend fetches them with the user's token (they are not public links).
        "download_url": reverse("chat-attachment-download", args=[a.pk]).removeprefix("/api/v1"),
        "thumbnail_url": reverse("chat-attachment-thumbnail", args=[a.pk]).removeprefix("/api/v1") if a.thumbnail else None,
    }


def reactions_data(message) -> list[dict]:
    by_emoji: dict[str, list] = {}
    for r in message.reactions.all():
        by_emoji.setdefault(r.emoji, []).append({"id": r.user_id, "full_name": r.user.full_name})
    return [{"emoji": e, "count": len(by_emoji[e]), "users": by_emoji[e]} for e in REACTIONS if e in by_emoji]


def reply_data(original) -> dict | None:
    if original is None:
        return None
    deleted = original.is_deleted
    return {
        "id": original.pk,
        "author": person(original.author),
        "body": "" if deleted else original.body[:PREVIEW_LENGTH],
        "deleted": deleted,
    }


def message_data(message) -> dict:
    deleted = message.is_deleted
    return {
        "id": message.pk,
        "conversation": message.conversation_id,
        "author": person(message.author),
        "body": "" if deleted else message.body,
        "reply_to": message.reply_to_id,
        "reply": reply_data(message.reply_to) if message.reply_to_id else None,
        "reactions": [] if deleted else reactions_data(message),
        "attachments": [] if deleted else [attachment_data(a) for a in message.attachments.all()],
        "created_at": message.created_at.isoformat(),
        "edited_at": message.edited_at.isoformat() if message.edited_at else None,
        "deleted": deleted,
        "editable_until": None if deleted else (message.created_at + EDIT_WINDOW).isoformat(),
    }


def preview_text(message) -> str:
    if message.body:
        return message.body[:PREVIEW_LENGTH]
    names = [a.original_name for a in message.attachments.all()]
    return f"📎 {', '.join(names)}"[:PREVIEW_LENGTH] if names else ""


def preview_data(message) -> dict | None:
    if message is None:
        return None
    deleted = message.is_deleted
    return {
        "id": message.pk,
        "author": person(message.author),
        "body": "" if deleted else preview_text(message),
        "deleted": deleted,
        "created_at": message.created_at.isoformat(),
    }


# ================================================================ live events


def _push_after_commit(messages: list[tuple[int, dict]]):
    def deliver():
        for user_id, data in messages:
            push(user_id, {"type": "chat.event", "data": data})

    transaction.on_commit(deliver)


def _send(user_ids, data: dict):
    _push_after_commit([(u, data) for u in user_ids])


def broadcast_message(message, event: str):
    """message.new / message.updated to every member, each with their own unread count."""
    fresh = with_details(Message.objects.filter(pk=message.pk)).get()
    unread = unread_by_member(message.conversation)
    payload = message_data(fresh)
    _push_after_commit([
        (user_id, {"type": "chat", "event": event, "conversation": message.conversation_id, "message": payload, "unread": count})
        for user_id, count in unread.items()
    ])


def notify_conversations_changed(user_ids, conversation_id):
    """Someone joined, left or was added/removed, or a channel changed: lists should refresh."""
    _send(list(user_ids), {"type": "chat", "event": "conversation.changed", "conversation": conversation_id})


def member_ids(conversation_id) -> list[int]:
    return list(Membership.objects.filter(conversation_id=conversation_id).values_list("user_id", flat=True))


def colleague_ids(user) -> set[int]:
    """People who share at least one conversation with the user (they may see the user's presence)."""
    mine = Membership.objects.filter(user=user).values("conversation")
    return set(Membership.objects.filter(conversation__in=mine).values_list("user_id", flat=True).distinct()) - {user.pk}


def typing_event(conversation_id, user) -> tuple[list[int], dict]:
    """Recipients (the other members) and the event for "<name> is typing"."""
    recipients = [u for u in member_ids(conversation_id) if u != user.pk]
    return recipients, {"type": "chat", "event": "typing", "conversation": conversation_id, "user": {"id": user.pk, "full_name": user.full_name}}


def presence_event(user, online: bool) -> tuple[set[int], dict]:
    return colleague_ids(user), {"type": "chat", "event": "presence", "user": user.pk, "online": online}


# ================================================================ messages


def save_attachments(message, uploader, files):
    """Check every file first (all or nothing), then store them privately with random names."""
    if len(files) > MAX_FILES_PER_MESSAGE:
        raise ValidationError({"files": [_("Send up to %(n)s files at a time.") % {"n": MAX_FILES_PER_MESSAGE}]})
    checked = []
    for upload in files:
        try:
            checked.append((upload, check_upload(upload)))
        except FileRejected as exc:
            raise ValidationError({"files": [str(exc)]})
    for upload, info in checked:
        attachment = MessageAttachment(
            message=message, original_name=upload.name[:255], size=upload.size,
            content_type=info.content_type, kind=info.kind, uploaded_by=uploader,
        )
        thumb = make_thumbnail(upload) if info.kind == "image" else None
        attachment.file.save(f"upload.{info.extension}", upload, save=False)
        if thumb:
            attachment.thumbnail.save("thumb.webp", thumb, save=False)
        attachment.save()


def send_message(conversation, author, body: str, reply_to=None, files=()) -> Message:
    with transaction.atomic():  # a refused file (checked before any is stored) leaves no message behind
        message = Message.objects.create(conversation=conversation, author=author, body=body, reply_to=reply_to)
        if files:
            save_attachments(message, author, files)
        Conversation.objects.filter(pk=conversation.pk).update(last_message_at=message.created_at)
        # Your own message is read by you.
        Membership.objects.filter(conversation=conversation, user=author).update(last_read_id=message.pk)
        broadcast_message(message, "message.new")
        transaction.on_commit(lambda: notify_new_message(message.pk))
    return message


def edit_message(message, body: str) -> Message:
    message.body = body
    message.edited_at = timezone.now()
    message.save(update_fields=["body", "edited_at"])
    broadcast_message(message, "message.updated")
    return message


def delete_message(message) -> Message:
    """The text, files and reactions are removed; the message keeps its place as "message deleted"."""
    with transaction.atomic():
        message.body = ""
        message.deleted_at = timezone.now()
        message.save(update_fields=["body", "deleted_at"])
        for attachment in message.attachments.all():
            attachment.delete()  # the post_delete signal removes the files
        message.reactions.all().delete()
        broadcast_message(message, "message.updated")
    return message


def toggle_reaction(message, user, emoji: str) -> bool:
    """Add the reaction, or remove it if the user already gave it. Returns True if it is now on."""
    if emoji not in REACTIONS:
        raise ValidationError({"emoji": [_("Choose one of the available reactions.")]})
    with transaction.atomic():
        removed, _count = Reaction.objects.filter(message=message, user=user, emoji=emoji).delete()
        if not removed:
            Reaction.objects.get_or_create(message=message, user=user, emoji=emoji)
        broadcast_message(message, "message.updated")
    return not removed


def mark_read(conversation, user, up_to: int | None = None) -> int:
    """Move the user's read position forward (never back). Returns their unread count afterwards.

    Chat notifications for this conversation are marked read too, so the bell matches.
    """
    newest = Message.objects.filter(conversation=conversation).order_by("-id").values_list("pk", flat=True).first() or 0
    target = newest if up_to is None else min(up_to, newest)
    Membership.objects.filter(conversation=conversation, user=user, last_read_id__lt=target).update(last_read_id=target)
    count = unread_by_member(conversation).get(user.pk, 0)
    events = [(user.pk, {"type": "chat", "event": "read", "conversation": conversation.pk, "unread": count})]
    if count == 0:
        cleared = Notification.objects.filter(
            recipient=user, is_read=False, link=f"/chat/{conversation.pk}",
            type__in=[NotificationType.DIRECT_MESSAGE, NotificationType.CHANNEL_MESSAGE],
        ).update(is_read=True)
        if cleared:
            remaining = Notification.objects.filter(recipient=user, is_read=False).count()
            events.append((user.pk, {"type": "unread_count", "count": remaining}))
    # The user's other tabs and devices clear their badges too.
    _push_after_commit(events)
    return count


def set_muted(conversation, user, muted: bool):
    Membership.objects.filter(conversation=conversation, user=user).update(muted=muted)
    _send([user.pk], {"type": "chat", "event": "conversation.changed", "conversation": conversation.pk})


# ================================================================ notifications


def notify_new_message(message_id):
    """In-app notification for each member who isn't looking at the conversation and hasn't muted it.

    Direct messages are emailed later, only if still unread (send_unread_dm_emails), never right away.
    """
    message = with_details(Message.objects.filter(pk=message_id).select_related("conversation")).first()
    if message is None or message.is_deleted:
        return
    conversation = message.conversation
    direct = conversation.kind == Conversation.Kind.DIRECT
    recipients = User.objects.filter(
        chat_memberships__conversation=conversation, chat_memberships__muted=False, is_active=True
    ).exclude(pk=message.author_id)
    params = {
        "actor": message.author.full_name if message.author else "",
        "preview": preview_text(message),
        "conversation": conversation.pk,
        "message": message.pk,
    }
    if not direct:
        params["channel"] = conversation.name
        params["general"] = conversation.is_default and conversation.channel_type == Conversation.ChannelType.GENERAL
    for user in recipients:
        if presence.is_viewing(user.pk, conversation.pk):
            continue
        notify(
            user,
            NotificationType.DIRECT_MESSAGE if direct else NotificationType.CHANNEL_MESSAGE,
            link=f"/chat/{conversation.pk}",
            actor=message.author,
            message="chat_direct" if direct else "chat_channel",
            params=params,
            email=False,
        )


def send_unread_dm_emails(now=None) -> int:
    """Email each person their direct messages left unread for DM_EMAIL_DELAY (one email per conversation).

    Each membership remembers the newest message already emailed, and the update is conditional,
    so a message is never emailed twice, even when two runs overlap.
    """
    now = now or timezone.now()
    window = Q(created_at__lte=now - DM_EMAIL_DELAY, created_at__gte=now - DM_EMAIL_LOOKBACK, deleted_at__isnull=True)
    pending = (
        Message.objects.filter(window, conversation=OuterRef("conversation"), id__gt=OuterRef("last_read_id"))
        .filter(id__gt=OuterRef("last_emailed_id"))
        .exclude(author_id=OuterRef("user"))
    )
    memberships = (
        Membership.objects.filter(conversation__kind=Conversation.Kind.DIRECT, muted=False, user__is_active=True)
        .exclude(user__email="")
        .filter(Exists(pending))
        .select_related("user")
    )
    sent = 0
    for membership in memberships:
        user = membership.user
        if not get_preferences(user).get(NotificationType.DIRECT_MESSAGE, {}).get("email"):
            continue
        messages = list(
            Message.objects.filter(window, conversation_id=membership.conversation_id)
            .filter(id__gt=max(membership.last_read_id, membership.last_emailed_id))
            .exclude(author=user)
            .select_related("author")
            .prefetch_related("attachments")
            .order_by("id")
        )
        if not messages:
            continue
        claimed = Membership.objects.filter(pk=membership.pk, last_emailed_id=membership.last_emailed_id).update(
            last_emailed_id=messages[-1].pk
        )
        if not claimed:
            continue  # another run got there first
        subject, body = render_dm_email(user, membership.conversation_id, messages)
        queue_email(subject, body, [user.email])
        sent += 1
    return sent


def render_dm_email(user, conversation_id, messages) -> tuple[str, str]:
    from apps.core.office_time import office_tz

    sender = messages[-1].author.full_name if messages[-1].author else _("A colleague")
    link = f"{settings.FRONTEND_URL.rstrip('/')}/chat/{conversation_id}"
    with translation.override(user.language or settings.LANGUAGE_CODE):
        lines = [_("You have unread messages from %(name)s:") % {"name": sender}, ""]
        for m in messages[-10:]:
            lines.append(f"  {m.created_at.astimezone(office_tz()):%H:%M}  {preview_text(m)}")
        if len(messages) > 10:
            lines.append("  " + _("…and %(n)s more") % {"n": len(messages) - 10})
        lines += ["", _("Reply in the CRM: %(link)s") % {"link": link}, "",
                  _("You get this email because direct-message emails are on in your notification settings.")]
        subject = _("Unread messages from %(name)s") % {"name": sender}
    return subject, "\n".join(lines)


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
    new = [Membership(conversation=conversation, user=u, last_read_id=newest, last_emailed_id=newest) for u in users if u.pk not in existing]
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
