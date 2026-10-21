"""Announcement operations: files, read receipts, and telling the audience."""
from collections import defaultdict

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Window
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext as _
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.core.email import queue_email
from apps.notifications.models import Notification, NotificationType
from apps.notifications.services import get_preferences, notify, push
from apps.core.photos import prepare_upload
from apps.tasks.files import FileRejected

from . import formatting, rules
from .models import Announcement, AnnouncementAttachment, AnnouncementRead

MAX_FILES = 10


def link(announcement) -> str:
    return f"/announcements/{announcement.pk}"


# ================================================================ files


def attachment_data(a) -> dict:
    return {
        "id": a.pk,
        "original_name": a.original_name,
        "size": a.size,
        "content_type": a.content_type,
        "kind": a.kind,
        # Relative API paths: the frontend fetches them with the user's token (they are not public links).
        "download_url": reverse("announcement-file-download", args=[a.pk]).removeprefix("/api/v1"),
        "thumbnail_url": reverse("announcement-file-thumbnail", args=[a.pk]).removeprefix("/api/v1") if a.thumbnail else None,
    }


def save_attachments(announcement, uploader, files, keep=0):
    """Check every file first (all or nothing), then store them privately with random names."""
    if keep + len(files) > MAX_FILES:
        raise ValidationError({"files": [_("An announcement can have up to %(n)s files.") % {"n": MAX_FILES}]})
    prepared = []
    for upload in files:
        try:
            prepared.append(prepare_upload(upload))  # images cleaned: upright, no GPS, camera or other metadata
        except FileRejected as exc:
            raise ValidationError({"files": [str(exc)]})
    for p in prepared:
        attachment = AnnouncementAttachment(
            announcement=announcement, original_name=p.upload.name[:255], size=p.size,
            content_type=p.info.content_type, kind=p.info.kind, uploaded_by=uploader,
        )
        attachment.file.save(f"upload.{p.info.extension}", p.content, save=False)
        if p.thumbnail:
            attachment.thumbnail.save("thumb.webp", p.thumbnail, save=False)
        attachment.save()


# ================================================================ read receipts


def mark_read(announcement, user) -> AnnouncementRead:
    """Record the first opening, and clear the person's notification about it."""
    read, created = AnnouncementRead.objects.get_or_create(announcement=announcement, user=user)
    if created:
        cleared = Notification.objects.filter(
            recipient=user, type=NotificationType.ANNOUNCEMENT, link=link(announcement), is_read=False
        ).update(is_read=True)
        if cleared:
            remaining = Notification.objects.filter(recipient=user, is_read=False).count()
            # The person's other tabs and devices update their badge too (same passthrough event as chat).
            push(user.pk, {"type": "chat.event", "data": {"type": "unread_count", "count": remaining}})
    return read


def receipt_counts(announcements) -> dict[int, dict]:
    """{announcement id: {"read": n, "total": n}} for a page of announcements, in two queries.

    Only people in the audience count (active, in a chosen department, not the author), so someone
    who moved department or left doesn't skew the numbers.
    """
    announcements = list(announcements)
    if not announcements:
        return {}
    ids = [a.pk for a in announcements]
    members = dict(
        User.objects.filter(is_active=True).values_list("department_id").annotate(n=Count("id")).values_list("department_id", "n")
    )
    everyone = sum(members.values())
    users = {}  # user id -> department id, for active readers
    reads = defaultdict(list)
    for announcement_id, user_id, department_id in AnnouncementRead.objects.filter(
        announcement_id__in=ids, user__is_active=True
    ).values_list("announcement_id", "user_id", "user__department_id"):
        reads[announcement_id].append(user_id)
        users[user_id] = department_id
    result = {}
    for a in announcements:
        if a.audience == Announcement.Audience.EVERYONE:
            in_audience = lambda dept: True  # noqa: E731
            total = everyone
        else:
            chosen = {d.pk for d in a.departments.all()}
            in_audience = chosen.__contains__
            total = sum(members.get(d, 0) for d in chosen)
        author = a.created_by  # select_related by the caller
        if author is not None and author.is_active and in_audience(author.department_id):
            total -= 1
        read = sum(1 for uid in reads[a.pk] if uid != a.created_by_id and in_audience(users[uid]))
        result[a.pk] = {"read": read, "total": max(total, 0)}
    return result


def receipts(announcement) -> dict:
    """Who in the audience has read it (with when) and who hasn't, by name."""
    reads = dict(AnnouncementRead.objects.filter(announcement=announcement).values_list("user_id", "read_at"))
    people = rules.audience_users(announcement).select_related("department").order_by("full_name", "id")
    read, unread = [], []
    for user in people:
        row = {"id": user.pk, "full_name": user.full_name, "department": user.department.name if user.department else None}
        if user.pk in reads:
            read.append({**row, "read_at": reads[user.pk].isoformat()})
        else:
            unread.append(row)
    read.sort(key=lambda r: r["read_at"], reverse=True)
    return {"read_count": len(read), "total": len(read) + len(unread), "read": read, "unread": unread}


# ================================================================ telling the audience


def publish(announcement, author):
    """The author has read their own announcement; the audience is told once the transaction commits."""
    AnnouncementRead.objects.get_or_create(announcement=announcement, user=author)
    pk = announcement.pk
    transaction.on_commit(lambda: notify_audience(pk))


def notify_audience(announcement_id: int) -> int:
    """In-app notification and email (each following the person's settings) for everyone in the audience."""
    announcement = (
        Announcement.objects.select_related("created_by").prefetch_related("departments", "attachments").filter(pk=announcement_id).first()
    )
    if announcement is None:
        return 0
    people = list(rules.audience_users(announcement))
    actor = announcement.created_by
    params = {
        "title": announcement.title,
        "actor": actor.full_name if actor else "",
        "preview": formatting.preview(announcement.body),
    }
    notify(people, NotificationType.ANNOUNCEMENT, link=link(announcement), actor=actor, message="announcement", params=params, email=False)
    sent = 0
    for user in people:
        if not user.email or not get_preferences(user).get(NotificationType.ANNOUNCEMENT, {}).get("email"):
            continue
        subject, body = render_email(user, announcement)
        queue_email(subject, body, [user.email])
        sent += 1
    return sent


def render_email(user, announcement) -> tuple[str, str]:
    url = f"{settings.FRONTEND_URL.rstrip('/')}{link(announcement)}"
    author = announcement.created_by.full_name if announcement.created_by else _("A colleague")
    with translation.override(user.language or settings.LANGUAGE_CODE):
        if announcement.audience == Announcement.Audience.DEPARTMENTS:
            names = ", ".join(d.name for d in announcement.departments.all())
            intro = _("%(name)s posted an announcement for %(departments)s:") % {"name": author, "departments": names}
        else:
            intro = _("%(name)s posted an announcement for everyone:") % {"name": author}
        lines = [intro, "", announcement.title, "=" * min(len(announcement.title), 60), "", formatting.plain_text(announcement.body)]
        files = [a.original_name for a in announcement.attachments.all()]
        if files:
            lines += ["", _("Attached files: %(files)s") % {"files": ", ".join(files)}]
        if announcement.expires_on:
            lines += ["", _("Shown on the board until %(date)s.") % {"date": announcement.expires_on.strftime("%d/%m/%Y")}]
        lines += ["", _("Read it in the CRM: %(link)s") % {"link": url}, "",
                  _("You get this email because announcement emails are on in your notification settings.")]
        subject = _("Announcement: %(title)s") % {"title": announcement.title}
    return subject, "\n".join(lines)


# ================================================================ dashboard


def unread_widget(user, limit=5) -> dict:
    """Current announcements for me that I haven't opened yet: pinned first, then newest.
    One query: the total comes from a window count over the same rows."""
    mine = AnnouncementRead.objects.filter(announcement=OuterRef("pk"), user=user)
    rows = list(
        rules.current(rules.visible_announcements(user))
        .filter(~Exists(mine))
        .select_related("created_by")
        .annotate(total=Window(Count("id")))
        .order_by("-pinned", "-published_at", "-id")[:limit]
    )
    items = [
        {
            "id": a.pk,
            "title": a.title,
            "pinned": a.pinned,
            "author": a.created_by.full_name if a.created_by else None,
            "published_at": a.published_at.isoformat(),
            "preview": formatting.preview(a.body, 120),
            "url": link(a),
        }
        for a in rows
    ]
    return {"unread": rows[0].total if rows else 0, "items": items}
