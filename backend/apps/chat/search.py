"""Message search across the conversations a person can read.

Never searches conversations the person can't read: private channels and direct messages they
aren't in (or have left), and archived conversations. Deleted messages are never found.

Every word must appear (case-insensitive, also inside longer words, so "quot" finds "quotation").
On PostgreSQL, web-search syntax also works ("price list", -draft, OR) through a full-text match
with the language-neutral "simple" configuration, so English and Urdu behave the same.
"""
from datetime import datetime, time

from django.db import connection
from django.db.models import Q

from apps.core.office_time import office_tz

from . import rules
from .models import Message

MIN_QUERY = 2


def searchable_conversations(user):
    return rules.readable_conversations(user).filter(archived_at__isnull=True)


def terms(q: str) -> list[str]:
    """Words to highlight and to require (quotes and web-search operators removed)."""
    words = []
    for raw in q.replace('"', " ").split():
        word = raw.lstrip("-")
        if word and word.upper() != "OR" and not raw.startswith("-"):
            words.append(word)
    return words


def search_messages(user, q: str, *, conversation=None, author=None, date_from=None, date_to=None):
    """Matching messages, newest first (a queryset)."""
    q = (q or "").strip()
    qs = Message.objects.filter(conversation__in=searchable_conversations(user), deleted_at__isnull=True)
    if conversation:
        qs = qs.filter(conversation_id=conversation)
    if author:
        qs = qs.filter(author_id=author)
    tz = office_tz()
    if date_from:
        qs = qs.filter(created_at__gte=datetime.combine(date_from, time.min, tzinfo=tz))
    if date_to:
        qs = qs.filter(created_at__lte=datetime.combine(date_to, time.max, tzinfo=tz))
    words = terms(q)
    every_word = Q()
    for word in words:
        every_word &= Q(body__icontains=word)
    if connection.vendor == "postgresql" and len(q) >= 3:
        from django.contrib.postgres.search import SearchQuery, SearchVector

        qs = qs.annotate(_doc=SearchVector("body", config="simple"))
        match = Q(_doc=SearchQuery(q, config="simple", search_type="websearch"))
        qs = qs.filter(every_word | match) if words else qs.filter(match)
    elif words:
        qs = qs.filter(every_word)
    else:
        return qs.none()
    return qs.order_by("-id")
