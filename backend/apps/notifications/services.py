import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.mail import send_mail
from django.utils import translation

from . import messages
from .models import DEFAULT_PREFERENCES, Notification, NotificationPreference

logger = logging.getLogger(__name__)


def user_group(user_id) -> str:
    return f"user_{user_id}"


def get_preferences(user) -> dict[str, dict[str, bool]]:
    prefs = {k: dict(v) for k, v in DEFAULT_PREFERENCES.items()}
    for p in NotificationPreference.objects.filter(user=user):
        prefs[p.type] = {"in_app": p.in_app, "email": p.email}
    return prefs


def display_text(notification: Notification) -> tuple[str, str]:
    """Title/body in the active language (falls back to the stored text)."""
    if notification.message_key in messages.RENDERERS:
        return messages.render(notification.message_key, notification.params)
    return notification.title, notification.body


def serialize(notification: Notification) -> dict:
    title, body = display_text(notification)
    return {
        "id": notification.pk,
        "type": notification.type,
        "title": title,
        "body": body,
        "link": notification.link,
        "is_read": notification.is_read,
        "actor_name": notification.actor.full_name if notification.actor else None,
        "created_at": notification.created_at.isoformat(),
    }


def push(user_id, message: dict):
    """Send an event to every open WebSocket of the user. Never raises."""
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(user_group(user_id), message)
    except Exception:  # a broken channel layer must not break the request
        logger.exception("Failed to push WebSocket event to user %s", user_id)


def notify(recipients, type, title="", body="", link="", actor=None, *, message=None, params=None) -> list[Notification]:
    """Create in-app notifications and send emails according to each recipient's preferences.

    Prefer ``message`` (a key in apps.notifications.messages) + ``params`` so the text
    follows each reader's language; plain ``title``/``body`` are shown as-is.
    The actor is never notified about their own action.
    """
    if hasattr(recipients, "pk"):  # a single user
        recipients = [recipients]
    params = params or {}
    created = []
    for user in {u for u in recipients if u is not None and u.is_active}:
        if actor is not None and user.pk == actor.pk:
            continue
        prefs = get_preferences(user).get(type, DEFAULT_PREFERENCES.get(type, {"in_app": True, "email": False}))
        with translation.override(user.language or settings.LANGUAGE_CODE):
            user_title, user_body = messages.render(message, params) if message else (title, body)
            if prefs["in_app"]:
                notification = Notification.objects.create(
                    recipient=user,
                    actor=actor,
                    type=type,
                    title=user_title,
                    body=user_body,
                    link=link,
                    message_key=message or "",
                    params=params,
                )
                created.append(notification)
                push(user.pk, {"type": "notification.new", "notification": serialize(notification)})
            if prefs["email"] and user.email:
                url = f"{settings.FRONTEND_URL}{link}" if link else settings.FRONTEND_URL
                send_mail(user_title, f"{user_body}\n\n{url}".strip(), None, [user.email], fail_silently=True)
    return created
