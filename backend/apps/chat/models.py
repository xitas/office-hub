"""Internal chat: channels and direct messages share one Conversation table.

- A channel has a name, a type (general / department / project) and is public or private.
  Default channels (General, one per department) have automatic membership.
- A direct message is a conversation of `kind=direct` between two people, found by `dm_key`.
  Group DMs can be added later as another kind with any number of members.
- Each member's read position (`Membership.last_read_id`) gives unread counts.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


class Conversation(models.Model):
    class Kind(models.TextChoices):
        CHANNEL = "channel", _("Channel")
        DIRECT = "direct", _("Direct message")

    class ChannelType(models.TextChoices):
        GENERAL = "general", _("General")
        DEPARTMENT = "department", _("Department")
        PROJECT = "project", _("Project")

    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.CHANNEL)
    name = models.CharField(max_length=80, blank=True)  # empty for direct messages
    description = models.CharField(max_length=300, blank=True)
    channel_type = models.CharField(max_length=12, choices=ChannelType.choices, blank=True)
    is_private = models.BooleanField(default=False)
    # Department channels belong to a department; managers manage their own department's channels.
    department = models.ForeignKey(
        "accounts.Department", null=True, blank=True, on_delete=models.SET_NULL, related_name="channels"
    )
    # General and the per-department channels: members follow the organization automatically.
    is_default = models.BooleanField(default=False)
    # Direct messages between two people: "<smaller id>:<larger id>", so each pair has one conversation.
    dm_key = models.CharField(max_length=40, null=True, blank=True, unique=True)
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, through="Membership", related_name="conversations")
    archived_at = models.DateTimeField(null=True, blank=True)
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        verbose_name = _("conversation")
        verbose_name_plural = _("conversations")
        constraints = [
            models.UniqueConstraint(
                fields=["channel_type"], condition=Q(is_default=True, channel_type="general"), name="chat_one_general_channel"
            ),
            models.UniqueConstraint(
                fields=["department"], condition=Q(is_default=True, channel_type="department"), name="chat_one_default_channel_per_department"
            ),
        ]

    def __str__(self):
        return self.name or f"DM {self.dm_key or self.pk}"

    @property
    def is_channel(self) -> bool:
        return self.kind == self.Kind.CHANNEL

    @property
    def archived(self) -> bool:
        return self.archived_at is not None


class Membership(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_memberships")
    # Id of the newest message this member has read (0 = none). Unread = newer messages by others.
    last_read_id = models.PositiveBigIntegerField(default=0)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["conversation", "user"], name="chat_unique_membership")]
        verbose_name = _("conversation member")
        verbose_name_plural = _("conversation members")

    def __str__(self):
        return f"{self.user} in {self.conversation}"


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    body = models.TextField()
    # Threads come later; the link is stored now so replies never need a migration of old data.
    reply_to = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="replies")
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    # Deleted messages keep their place in the conversation ("message deleted"); the text is removed.
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["conversation", "-id"], name="chat_message_history_idx")]
        verbose_name = _("message")
        verbose_name_plural = _("messages")

    def __str__(self):
        return self.body[:40]

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
