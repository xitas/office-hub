from django.utils.translation import gettext as _
from rest_framework import serializers

from apps.accounts.models import Department, User

from . import rules, services
from .models import Conversation, Message

MAX_BODY = 4000


class ConversationSerializer(serializers.ModelSerializer):
    """A channel or direct message as seen by the current user (annotated by the view)."""

    is_member = serializers.BooleanField(read_only=True, default=False)
    muted = serializers.BooleanField(read_only=True, default=False)
    last_read_id = serializers.IntegerField(read_only=True, default=0, help_text="Your read position (for the unread divider).")
    unread_count = serializers.IntegerField(read_only=True, default=0)
    member_count = serializers.IntegerField(read_only=True, default=0)
    archived = serializers.BooleanField(read_only=True)
    last_message = serializers.SerializerMethodField()
    other_person = serializers.SerializerMethodField(help_text="Direct messages: the other person.")
    department_name = serializers.CharField(source="department.name", default=None, read_only=True)
    can_manage = serializers.SerializerMethodField()
    can_post = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            "id", "kind", "name", "description", "channel_type", "is_private", "is_default", "department",
            "department_name", "archived", "is_member", "muted", "last_read_id", "member_count", "unread_count", "last_message",
            "last_message_at", "other_person", "can_manage", "can_post", "created_at",
        ]
        read_only_fields = fields

    def get_last_message(self, obj) -> dict | None:
        return services.preview_data(self.context.get("last_messages", {}).get(obj.pk))

    def get_other_person(self, obj) -> dict | None:
        if obj.kind != Conversation.Kind.DIRECT:
            return None
        me = self.context["request"].user
        others = [m.user for m in getattr(obj, "member_list", []) if m.user_id != me.pk]
        return services.person(others[0]) if others else services.person(me)  # a note to yourself

    def get_can_manage(self, obj) -> bool:
        return rules.can_manage(self.context["request"].user, obj)

    def get_can_post(self, obj) -> bool:
        return rules.can_post(self.context["request"].user, obj, member=getattr(obj, "is_member", False))


class ChannelWriteSerializer(serializers.ModelSerializer):
    """Create or change a channel (not the automatic membership of default channels)."""

    department = serializers.PrimaryKeyRelatedField(queryset=Department.objects.all(), required=False, allow_null=True)
    channel_type = serializers.ChoiceField(choices=Conversation.ChannelType.choices, default=Conversation.ChannelType.PROJECT)
    member_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=User.objects.filter(is_active=True), required=False, write_only=True, source="initial_members"
    )

    class Meta:
        model = Conversation
        fields = ["id", "name", "description", "channel_type", "is_private", "department", "member_ids"]

    def validate_name(self, value):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError(_("This field may not be blank."))
        return value

    def validate(self, attrs):
        user = self.context["request"].user
        if self.instance is None:
            channel_type = attrs.get("channel_type", Conversation.ChannelType.PROJECT)
            if channel_type == Conversation.ChannelType.GENERAL and not rules.is_admin(user):
                raise serializers.ValidationError({"channel_type": _("Only admins can create general channels.")})
            # Managers create channels for their own department.
            if not rules.is_admin(user) and "department" not in attrs:
                attrs["department"] = user.department
            department = attrs.get("department")
            if not rules.can_create_channel(user, channel_type, department.pk if department else None):
                raise serializers.ValidationError(_("You can only create channels for your own department."))
        else:
            if self.instance.is_default:
                for field in ("channel_type", "department", "is_private"):
                    if field in attrs and attrs[field] != getattr(self.instance, field):
                        raise serializers.ValidationError({field: _("This can't be changed on a default channel.")})
            if "department" in attrs and not rules.is_admin(user) and attrs["department"] != self.instance.department:
                raise serializers.ValidationError({"department": _("Only admins can move a channel to another department.")})
            if attrs.get("channel_type") == Conversation.ChannelType.GENERAL and not rules.is_admin(user):
                raise serializers.ValidationError({"channel_type": _("Only admins can create general channels.")})
            attrs.pop("initial_members", None)
        return attrs


class MessageSerializer(serializers.ModelSerializer):
    """Send: text and/or files (multipart `files`), optionally replying to a message. Edit: text only."""

    body = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False, default="")

    class Meta:
        model = Message
        fields = ["id", "body", "reply_to"]

    def to_representation(self, instance):
        return services.message_data(instance)

    def validate_body(self, value):
        value = value.strip()
        if not value and not self.context.get("has_files"):
            raise serializers.ValidationError(_("Write a message first."))
        if len(value) > MAX_BODY:
            raise serializers.ValidationError(_("Messages can be up to %(n)s characters.") % {"n": MAX_BODY})
        return value

    def validate_reply_to(self, value):
        conversation = self.context.get("conversation")
        if value is not None and conversation is not None and value.conversation_id != conversation.pk:
            raise serializers.ValidationError(_("You can only reply to a message in this conversation."))
        return value
