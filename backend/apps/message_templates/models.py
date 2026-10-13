"""Reusable message texts (quotations, reminders, thank-you notes) with placeholders.

A template is shared with everyone, with one department, or kept personal. Placeholders such as
{contact.first_name} or {my.phone} are filled from a contact and the person using it
(see placeholders.py). Usage is counted so popular templates come first.
"""
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class MessageTemplate(models.Model):
    class Category(models.TextChoices):
        QUOTATION = "quotation", _("Quotation")
        REMINDER = "reminder", _("Reminder")
        THANK_YOU = "thank_you", _("Thank you")
        FOLLOW_UP = "follow_up", _("Follow-up")
        GENERAL = "general", _("General")

    class Channel(models.TextChoices):
        EMAIL = "email", _("Email")
        WHATSAPP = "whatsapp", _("WhatsApp")
        CHAT = "chat", _("Chat")
        ANY = "any", _("Any")

    class Language(models.TextChoices):
        ENGLISH = "en", _("English")
        URDU = "ur", _("Urdu")

    class Sharing(models.TextChoices):
        EVERYONE = "everyone", _("Everyone")
        DEPARTMENT = "department", _("My department")
        PERSONAL = "personal", _("Only me")

    name = models.CharField(max_length=120)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.GENERAL, db_index=True)
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.ANY, db_index=True)
    language = models.CharField(max_length=2, choices=Language.choices, default=Language.ENGLISH)
    subject = models.CharField(max_length=200, blank=True)  # email only
    body = models.TextField()
    sharing = models.CharField(max_length=12, choices=Sharing.choices, default=Sharing.PERSONAL, db_index=True)
    # The department a "department" template is shared with (the creator's at the time).
    department = models.ForeignKey("accounts.Department", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="message_templates")
    archived_at = models.DateTimeField(null=True, blank=True)
    usage_count = models.PositiveIntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-usage_count", "name", "id"]
        verbose_name = _("message template")
        verbose_name_plural = _("message templates")

    def __str__(self):
        return self.name
