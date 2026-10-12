"""@mentions in chat.

- `@[Full Name](user:12)` (written by the mention picker) names a person. Only people who can
  read the conversation count: members, or anyone for a public channel. Anyone else is plain text.
- `@channel` notifies every member and `@here` the members online right now. Only people who manage
  the channel (its department's manager, or an admin) may use them; a large channel needs an
  explicit confirmation (BROADCAST_CONFIRM_ABOVE).
- Mentions are stored per person (MessageMention), so "Mentions" lists, unread counts and the
  delayed email can find them. Being mentioned notifies you even in a muted conversation.
"""
import re

from django.db import transaction

from apps.accounts.models import User

from . import presence, rules
from .models import Conversation, Membership, MessageMention

MENTION_RE = re.compile(r"@\[([^\]\n]{1,150})\]\(user:(\d+)\)")
BROADCAST_RE = re.compile(r"(?<![\w@\[])@(channel|here)\b")
BROADCAST_CONFIRM_ABOVE = 10  # members; @channel/@here in a bigger channel asks "notify N people?" first


def plain_text(body: str) -> str:
    """The body as people read it: tokens become "@Full Name"."""
    return MENTION_RE.sub(lambda m: f"@{m.group(1)}", body or "")


def named_ids(body: str) -> set[int]:
    return {int(m.group(2)) for m in MENTION_RE.finditer(body or "")}


def broadcast_kind(body: str, conversation) -> str | None:
    """"channel", "here" or None. Only channels have them (in a direct message the words are just text)."""
    if not conversation.is_channel:
        return None
    kinds = {m.group(1) for m in BROADCAST_RE.finditer(body or "")}
    return "channel" if "channel" in kinds else ("here" if "here" in kinds else None)


def can_broadcast(user, conversation) -> bool:
    return conversation.is_channel and rules.can_manage(user, conversation)


def mentionable(conversation):
    """People who may be mentioned: those who can read the conversation (active users only)."""
    people = User.objects.filter(is_active=True)
    if conversation.is_channel and not conversation.is_private:
        return people
    return people.filter(chat_memberships__conversation=conversation)


def suggestions(conversation, q: str = "", limit: int = 8):
    people = mentionable(conversation)
    q = q.strip()
    if q:
        people = people.filter(full_name__icontains=q)
    # Members first, then alphabetical.
    member_ids = set(Membership.objects.filter(conversation=conversation).values_list("user_id", flat=True))
    found = list(people.order_by("full_name")[:200])
    found.sort(key=lambda u: (u.pk not in member_ids, u.full_name.lower()))
    return found[:limit]


def resolve(message) -> dict[int, str]:
    """{user_id: kind} for everyone this message mentions (never its author)."""
    conversation = message.conversation
    targets: dict[int, str] = {}
    kind = broadcast_kind(message.body, conversation)
    if kind and message.author and can_broadcast(message.author, conversation):
        members = set(Membership.objects.filter(conversation=conversation, user__is_active=True).values_list("user_id", flat=True))
        reached = members if kind == "channel" else presence.online_ids(members)
        targets.update({uid: kind for uid in reached})
    named = named_ids(message.body)
    if named:
        for uid in mentionable(conversation).filter(pk__in=named).values_list("pk", flat=True):
            targets[uid] = MessageMention.Kind.DIRECT  # being named beats being reached by @channel
    targets.pop(message.author_id, None)
    return targets


@transaction.atomic
def record(message) -> set[int]:
    """Store who the message mentions now (after sending or editing). Returns the newly mentioned people."""
    targets = resolve(message)
    existing = dict(MessageMention.objects.filter(message=message).values_list("user_id", "kind"))
    MessageMention.objects.filter(message=message).exclude(user_id__in=targets).delete()
    for uid, kind in targets.items():
        if uid not in existing:
            MessageMention.objects.create(message=message, user_id=uid, kind=kind)
        elif existing[uid] != kind:
            MessageMention.objects.filter(message=message, user_id=uid).update(kind=kind)
    return set(targets) - set(existing)


def conversation_kind(conversation) -> str:
    return "direct" if conversation.kind == Conversation.Kind.DIRECT else "channel"
