"""Chat in the rest of the CRM: global search, record link cards and dashboard widgets.

Everything here is scoped to what the viewer may read, so nobody learns about conversations
or records they couldn't open.
"""
from django.db.models import Exists, OuterRef, Subquery
from django.utils.translation import gettext as _

from apps.core.permissions import has_perm

from . import mentions, search, services
from .models import Conversation, Membership, Message, MessageMention

DASHBOARD_LIMIT = 5


def conversation_title(conversation, viewer, others: dict | None = None) -> str:
    """What the viewer calls the conversation: the other person for a direct message.
    `others` ({conversation id: other person}) saves a query per direct message in lists."""
    if conversation.kind == Conversation.Kind.DIRECT:
        if others is not None:
            other = others.get(conversation.pk)
            return other.full_name if other else viewer.full_name
        other = (
            Membership.objects.filter(conversation=conversation).exclude(user=viewer).select_related("user").first()
        )
        return other.user.full_name if other else viewer.full_name
    if conversation.is_default and conversation.channel_type == Conversation.ChannelType.GENERAL:
        return f"#{_('General')}"
    return f"#{conversation.name}"


def snippet(body: str, words: list[str], width: int = 140) -> str:
    """A short piece of the message around the first match (plain text: mention tokens as "@Name")."""
    text = mentions.plain_text(body)
    lower = text.lower()
    at = min((lower.find(w.lower()) for w in words if lower.find(w.lower()) >= 0), default=0)
    start = max(0, at - width // 3)
    piece = text[start:start + width]
    return ("…" if start else "") + piece + ("…" if start + width < len(text) else "")


# ================================================================ global search


def search_queryset(user):
    return (
        Message.objects.filter(conversation__in=search.searchable_conversations(user), deleted_at__isnull=True)
        .select_related("author", "conversation")
        .order_by("-id")
    )


def search_hit(message, viewer) -> dict:
    author = message.author.full_name if message.author else _("A colleague")
    if message.conversation.kind == Conversation.Kind.DIRECT:
        title = f"{conversation_title(message.conversation, viewer)} · {_('Direct message')}"
    else:
        title = f"{author} · {conversation_title(message.conversation, viewer)}"
    return {
        "id": message.pk,
        "title": title,
        "subtitle": snippet(message.body, []),
        "url": f"/chat/{message.conversation_id}?message={message.pk}",
        "created_at": message.created_at.isoformat(),
    }


# ================================================================ record link cards


def record_card(user, kind: str, pk: int) -> dict | None:
    """Title and status of a task, contact or company the user can see; None otherwise."""
    if kind == "task":
        if not has_perm(user, "tasks", "view"):
            return None
        from apps.tasks.rules import visible_tasks

        task = visible_tasks(user).filter(pk=pk).first()
        if task is None:
            return None
        return {
            "type": "task", "id": task.pk, "title": task.title, "url": f"/tasks/{task.pk}",
            "status": task.status, "status_label": task.get_status_display(),
            "due_date": task.due_date.isoformat() if task.due_date else None, "is_overdue": task.is_overdue,
        }
    if kind in ("contact", "company"):
        if not has_perm(user, "contacts", "view"):
            return None
        from apps.contacts.visibility import visible_companies, visible_contacts

        if kind == "contact":
            contact = visible_contacts(user).select_related("company").filter(pk=pk).first()
            if contact is None:
                return None
            return {
                "type": "contact", "id": contact.pk, "title": contact.full_name, "url": f"/contacts/{contact.pk}",
                "status": contact.status, "status_label": contact.get_status_display(),
                "subtitle": contact.company.name if contact.company else "",
            }
        company = visible_companies(user).filter(pk=pk).first()
        if company is None:
            return None
        return {
            "type": "company", "id": company.pk, "title": company.name, "url": f"/companies/{company.pk}",
            "status": None, "status_label": None, "subtitle": " · ".join(filter(None, [company.industry, company.city])),
        }
    return None


# ================================================================ dashboard


def unread_messages(user):
    """Conversations with unread messages (muted and archived left out), newest activity first."""
    if not has_perm(user, "chat", "view"):
        return None
    latest = Message.objects.filter(conversation=OuterRef("conversation"), deleted_at__isnull=True).order_by("-id").values("id")[:1]
    mine = list(
        Membership.objects.filter(user=user, muted=False, conversation__archived_at__isnull=True)
        .annotate(unread=services.unread_count_expr(), last_id=Subquery(latest))
        .filter(unread__gt=0)
        .select_related("conversation")
        .order_by("-conversation__last_message_at")[:DASHBOARD_LIMIT]
    )
    # A fixed number of queries however many conversations are listed.
    lasts = {m.pk: m for m in Message.objects.filter(pk__in=[x.last_id for x in mine if x.last_id]).select_related("author").prefetch_related("attachments")}
    others = {
        m.conversation_id: m.user
        for m in Membership.objects.filter(conversation__in=[x.conversation_id for x in mine], conversation__kind=Conversation.Kind.DIRECT)
        .exclude(user=user).select_related("user")
    }
    items = []
    for membership in mine:
        conversation = membership.conversation
        last = lasts.get(membership.last_id)
        who = f"{last.author.full_name.split(' ')[0]}: " if last and last.author and conversation.is_channel else ""
        items.append({
            "id": conversation.pk,
            "title": conversation_title(conversation, user, others),
            "subtitle": f"{who}{services.preview_text(last)}" if last else "",
            "url": f"/chat/{conversation.pk}",
            "badge": str(membership.unread),
            "time": last.created_at.isoformat() if last else None,
        })
    return items


def unread_mentions_count(user) -> int:
    """Mentions of the user in messages they haven't read yet (in conversations they still belong to)."""
    unread_here = Membership.objects.filter(
        conversation=OuterRef("message__conversation"), user=user, last_read_id__lt=OuterRef("message_id"),
        conversation__archived_at__isnull=True,
    )
    return MessageMention.objects.filter(user=user, message__deleted_at__isnull=True).filter(Exists(unread_here)).count()


def chat_mentions(user):
    if not has_perm(user, "chat", "view"):
        return None
    return {"unread": unread_mentions_count(user)}


def register():
    from apps.core import search as global_search
    from apps.dashboard import registry as dashboard

    dashboard.register("unread_messages", unread_messages)
    dashboard.register("chat_mentions", chat_mentions)
    global_search.register(
        "messages", queryset=search_queryset, fields=["body"], serialize=search_hit, permission=("chat", "view"),
    )
