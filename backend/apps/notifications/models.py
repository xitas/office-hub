from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class NotificationType(models.TextChoices):
    TASK_ASSIGNED = "task_assigned", _("Task assigned to me")
    TASK_STATUS = "task_status", _("Task status changed")
    TASK_COMMENT = "task_comment", _("New comment on my task")
    TASK_DEADLINE = "task_deadline", _("Task deadline approaching")
    TASK_OVERDUE = "task_overdue", _("Task overdue")
    DAILY_DIGEST = "daily_digest", _("Morning digest (email)")
    MENTION = "mention", _("Mentioned in a task comment")
    CHAT_MENTION = "chat_mention", _("Mentioned in chat")
    DIRECT_MESSAGE = "direct_message", _("New direct message")
    CHANNEL_MESSAGE = "channel_message", _("New message in my channels")
    FOLLOW_UP = "follow_up", _("Client follow-up due")
    APPROVAL_REQUEST = "approval_request", _("Approval requested")
    APPROVAL_RESULT = "approval_result", _("My request approved/rejected")
    ANNOUNCEMENT = "announcement", _("New announcement")
    BOOKING = "booking", _("Booking updates")
    MEETING = "meeting", _("Meeting invitations, changes and reminders")
    OFFICE_EVENT = "office_event", _("Office events and holidays")
    ATTENDANCE = "attendance", _("Attendance reminders and corrections")
    LOW_STOCK = "low_stock", _("Low-stock alerts (supplies)")
    VISIT = "visit", _("Field visit updates")
    SYSTEM = "system", _("System and security")


# Default channels per type when the user has not saved a preference.
DEFAULT_PREFERENCES = {
    t.value: {"in_app": True, "email": t.value in {"task_assigned", "approval_request", "approval_result", "system"}}
    for t in NotificationType
}
# Direct messages: email only when one is left unread for a while (see apps.chat.tasks); channel messages never email.
DEFAULT_PREFERENCES["direct_message"] = {"in_app": True, "email": True}
# Chat mentions: emailed only if left unread for a while (see apps.chat.tasks).
DEFAULT_PREFERENCES["chat_mention"] = {"in_app": True, "email": True}
# Announcements are emailed by default (each person can turn it off).
DEFAULT_PREFERENCES["announcement"] = {"in_app": True, "email": True}
# Meeting invitations and changes are emailed by default; office events and holidays are in-app only.
DEFAULT_PREFERENCES["meeting"] = {"in_app": True, "email": True}
# The digest is an email only.
DEFAULT_PREFERENCES["daily_digest"] = {"in_app": False, "email": True}


class Notification(models.Model):
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    type = models.CharField(max_length=30, choices=NotificationType.choices, default=NotificationType.SYSTEM)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    link = models.CharField(max_length=255, blank=True, help_text="Frontend route to open, e.g. /tasks/12")
    # When set, title/body are re-rendered from apps.notifications.messages in the reader's language;
    # the stored title/body are the recipient-language rendering kept as a fallback.
    message_key = models.CharField(max_length=50, blank=True)
    params = models.JSONField(default=dict, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("notification")
        verbose_name_plural = _("notifications")
        indexes = [models.Index(fields=["recipient", "is_read", "-created_at"])]

    def __str__(self):
        return f"{self.recipient}: {self.title}"


class NotificationPreference(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_preferences")
    type = models.CharField(max_length=30, choices=NotificationType.choices)
    in_app = models.BooleanField(default=True)
    email = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "type"], name="unique_notification_pref")]
        verbose_name = _("notification preference")
        verbose_name_plural = _("notification preferences")

    def __str__(self):
        return f"{self.user} {self.type}"
