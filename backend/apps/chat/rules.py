"""Who sees, reads, posts in and manages conversations.

- Public channels: everyone can see and read them, and join (non-default ones).
- Private channels and direct messages: members only. Admins also see private channels in the
  channel list so they can manage them, but read their messages only if they are members.
- Posting: members of a conversation that isn't archived.
- Managing a channel (rename, privacy, members, archive): admins any channel; managers the
  channels of their own department. Default channels' members are automatic.
- Creating channels: admins any type; managers department or project channels for their department.
- Anyone can start a direct message with any active colleague.
"""
from django.db.models import Q

from apps.core.permissions import ADMIN, MANAGER

from .models import Conversation, Membership


def is_admin(user) -> bool:
    return user.role == ADMIN or user.is_superuser


def is_member(user, conversation) -> bool:
    return Membership.objects.filter(conversation=conversation, user=user).exists()


def visible_conversations(user):
    """Conversations this user may see in lists (not necessarily read)."""
    q = Q(memberships__user=user) | Q(kind=Conversation.Kind.CHANNEL, is_private=False)
    if is_admin(user):
        q |= Q(kind=Conversation.Kind.CHANNEL)
    return Conversation.objects.filter(pk__in=Conversation.objects.filter(q).values("pk"))


def readable_conversations(user):
    """Conversations whose messages this user may read."""
    q = Q(memberships__user=user) | Q(kind=Conversation.Kind.CHANNEL, is_private=False)
    return Conversation.objects.filter(pk__in=Conversation.objects.filter(q).values("pk"))


def can_post(user, conversation, member: bool | None = None) -> bool:
    if conversation.archived:
        return False
    return is_member(user, conversation) if member is None else member


def can_manage(user, conversation) -> bool:
    if not conversation.is_channel:
        return False
    if is_admin(user):
        return True
    return (
        user.role == MANAGER
        and user.department_id is not None
        and conversation.department_id == user.department_id
        and conversation.channel_type != Conversation.ChannelType.GENERAL
    )


def can_create_channel(user, channel_type: str, department_id) -> bool:
    if is_admin(user):
        return True
    return (
        user.role == MANAGER
        and user.department_id is not None
        and channel_type in (Conversation.ChannelType.DEPARTMENT, Conversation.ChannelType.PROJECT)
        and department_id == user.department_id
    )
