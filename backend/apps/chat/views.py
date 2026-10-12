from django.db.models import Count, Exists, F, IntegerField, Max, OuterRef, Prefetch, Subquery
from django.db.models.functions import Coalesce
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.views import APIView
from rest_framework.pagination import CursorPagination
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from apps.accounts.models import User
from apps.core.audit import log_action
from apps.core.models import AuditLog
from apps.core.permissions import ModulePermission
from apps.core.safe_cache import safe_cache

from . import integration, mentions, presence, rules, services
from .search import MIN_QUERY, search_messages, terms
from .models import REACTIONS, Conversation, Membership, Message, MessageAttachment
from .serializers import ChannelWriteSerializer, ConversationSerializer, MessageSerializer


class ChatSendThrottle(UserRateThrottle):
    """Messages sent per user (default 30 a minute). Keeps working per process if Redis is down."""

    scope = "chat_send"
    cache = safe_cache


class MessageHistoryPagination(CursorPagination):
    """Newest first; follow `next` to load older messages. Stable while new messages arrive."""

    ordering = "-id"
    page_size = 30
    page_size_query_param = "page_size"
    max_page_size = 100


class UserIdsSerializer(serializers.Serializer):
    user_ids = serializers.ListField(child=serializers.IntegerField())


class DirectSerializer(serializers.Serializer):
    user = serializers.IntegerField()


class MuteSerializer(serializers.Serializer):
    muted = serializers.BooleanField()


class ReactSerializer(serializers.Serializer):
    emoji = serializers.ChoiceField(choices=REACTIONS)


class ReadSerializer(serializers.Serializer):
    message = serializers.IntegerField(required=False, help_text="Default: the newest message")


AROUND = 15  # messages shown on each side of a message opened "in context"


def check_broadcast(request, conversation, body: str):
    """@channel / @here: channel managers and admins only; a large channel needs `confirm_broadcast`."""
    kind = mentions.broadcast_kind(body, conversation)
    if not kind:
        return
    if not mentions.can_broadcast(request.user, conversation):
        raise ValidationError({"body": [_("Only the channel's manager or an admin can use @channel and @here.")]})
    members = Membership.objects.filter(conversation=conversation).count()
    confirmed = str(request.data.get("confirm_broadcast", "")).lower() in ("1", "true", "yes")
    if members > mentions.BROADCAST_CONFIRM_ABOVE and not confirmed:
        raise ValidationError({
            "confirm_broadcast": [_("This notifies %(n)s people. Confirm to send.") % {"n": members}],
            "members": members,
        })


def found_item(message, viewer, titles: dict) -> dict:
    """A message in "Mentions" or search results, with where it was said."""
    conversation = message.conversation
    if conversation.pk not in titles:
        titles[conversation.pk] = integration.conversation_title(conversation, viewer)
    return {**services.message_data(message), "conversation_title": titles[conversation.pk], "conversation_kind": conversation.kind}


class FoundPagination(CursorPagination):
    ordering = "-id"
    page_size = 20


def _names(users) -> str:
    return ", ".join(sorted(u.full_name for u in users))


class ConversationViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet
):
    """Channels and direct messages.

    List: your conversations (newest activity first) with unread counts and the last message;
    `?scope=browse` lists channels you can see but haven't joined. Create/update: channels
    (admins any; managers their department's). Direct messages: POST /chat/conversations/direct/.
    """

    module = "chat"
    permission_classes = [ModulePermission]
    pagination_class = None  # a person's conversations are a short list
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_serializer_class(self):
        if self.action in ("create", "partial_update", "update"):
            return ChannelWriteSerializer
        if self.action == "messages":
            return MessageSerializer
        return ConversationSerializer

    def get_throttles(self):
        if self.action == "messages" and self.request.method == "POST":
            return [ChatSendThrottle()]
        return super().get_throttles()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Conversation.objects.none()
        user = self.request.user
        mine = Membership.objects.filter(conversation=OuterRef("pk"), user=user)
        return (
            rules.visible_conversations(user)
            .select_related("department")
            .annotate(
                is_member=Exists(mine),
                muted=Coalesce(Subquery(mine.values("muted")[:1]), False),
                last_read_id=Coalesce(Subquery(mine.values("last_read_id")[:1]), 0),
                unread_count=Coalesce(Subquery(mine.annotate(n=services.unread_count_expr()).values("n")[:1], output_field=IntegerField()), 0),
                member_count=Coalesce(
                    Subquery(
                        Membership.objects.filter(conversation=OuterRef("pk")).order_by().values("conversation")
                        .annotate(n=Count("pk")).values("n"),
                        output_field=IntegerField(),
                    ),
                    0,
                ),
                last_message_id=Max("messages__id"),
            )
            .prefetch_related(
                Prefetch(
                    "memberships",
                    queryset=Membership.objects.filter(conversation__kind=Conversation.Kind.DIRECT).select_related("user"),
                    to_attr="member_list",
                )
            )
            .order_by(F("last_message_at").desc(nulls_last=True), "name", "id")
        )

    def _context_for(self, conversations):
        ids = [c.last_message_id for c in conversations if c.last_message_id]
        last = {m.conversation_id: m for m in Message.objects.filter(pk__in=ids).select_related("author")}
        return {**self.get_serializer_context(), "last_messages": last}

    @extend_schema(parameters=[
        OpenApiParameter("scope", str, enum=["mine", "browse"]),
        OpenApiParameter("archived", bool, description="Include archived conversations"),
    ])
    def list(self, request):
        qs = self.get_queryset()
        if request.query_params.get("archived") not in ("true", "1"):
            qs = qs.filter(archived_at__isnull=True)
        if request.query_params.get("scope") == "browse":
            qs = qs.filter(kind=Conversation.Kind.CHANNEL, is_member=False)
        else:
            qs = qs.filter(is_member=True)
        conversations = list(qs)
        return Response(ConversationSerializer(conversations, many=True, context=self._context_for(conversations)).data)

    def retrieve(self, request, pk=None):
        conversation = self.get_object()
        return Response(ConversationSerializer(conversation, context=self._context_for([conversation])).data)

    def _reload(self, conversation):
        fresh = self.get_queryset().get(pk=conversation.pk)
        return ConversationSerializer(fresh, context=self._context_for([fresh])).data

    # ------------------------------------------------------------ channels

    def create(self, request):
        serializer = ChannelWriteSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        initial = serializer.validated_data.pop("initial_members", [])
        channel = serializer.save(kind=Conversation.Kind.CHANNEL, created_by=request.user)
        services.add_members(channel, {request.user, *initial})
        log_action(request.user, AuditLog.Action.CREATE, channel, request=request, changes={
            "name": channel.name, "channel_type": channel.channel_type, "is_private": channel.is_private,
            "department": str(channel.department) if channel.department else None,
            "members": _names(User.objects.filter(chat_memberships__conversation=channel)),
        })
        return Response(self._reload(channel), status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        channel = self.get_object()
        if not rules.can_manage(request.user, channel):
            raise PermissionDenied(_("You can't change this channel."))
        tracked = ("name", "description", "channel_type", "is_private", "department_id")
        before = {f: getattr(channel, f) for f in tracked}
        serializer = ChannelWriteSerializer(channel, data=request.data, partial=True, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        serializer.save()
        changes = {f.removesuffix("_id"): [before[f], getattr(channel, f)] for f in tracked if before[f] != getattr(channel, f)}
        if changes:
            log_action(request.user, AuditLog.Action.UPDATE, channel, changes=changes, request=request)
            services.notify_conversations_changed(channel.memberships.values_list("user_id", flat=True), channel.pk)
        return Response(self._reload(channel))

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    def _managed_channel(self, request):
        channel = self.get_object()
        if not rules.can_manage(request.user, channel):
            raise PermissionDenied(_("You can't change this channel."))
        return channel

    @extend_schema(request=None, responses={200: ConversationSerializer})
    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        """Archived channels are read-only and leave everyone's list. Default channels can't be archived."""
        channel = self._managed_channel(request)
        if channel.is_default:
            raise ValidationError({"detail": _("Default channels can't be archived.")})
        if not channel.archived:
            channel.archived_at = timezone.now()
            channel.save(update_fields=["archived_at", "updated_at"])
            log_action(request.user, AuditLog.Action.UPDATE, channel, changes={"archived": [False, True]}, request=request)
            services.notify_conversations_changed(channel.memberships.values_list("user_id", flat=True), channel.pk)
        return Response(self._reload(channel))

    @extend_schema(request=None, responses={200: ConversationSerializer})
    @action(detail=True, methods=["post"])
    def unarchive(self, request, pk=None):
        channel = self._managed_channel(request)
        if channel.archived:
            channel.archived_at = None
            channel.save(update_fields=["archived_at", "updated_at"])
            log_action(request.user, AuditLog.Action.UPDATE, channel, changes={"archived": [True, False]}, request=request)
            services.notify_conversations_changed(channel.memberships.values_list("user_id", flat=True), channel.pk)
        return Response(self._reload(channel))

    @extend_schema(request=UserIdsSerializer, responses={200: dict})
    @action(detail=True, methods=["get", "post"])
    def members(self, request, pk=None):
        """GET: the members (anyone who can read the conversation). POST {"user_ids": [...]}: add people."""
        conversation = self.get_object()
        if request.method == "GET":
            if not rules.readable_conversations(request.user).filter(pk=conversation.pk).exists() and not rules.can_manage(request.user, conversation):
                raise PermissionDenied()
            people = User.objects.filter(chat_memberships__conversation=conversation).order_by("full_name")
            return Response([services.person(u) for u in people])
        channel = self._managed_channel(request)
        if channel.is_default:
            raise ValidationError({"detail": _("Members of default channels follow the organization automatically.")})
        ids = request.data.get("user_ids") or []
        if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
            raise ValidationError({"user_ids": _("Give a list of people.")})
        users = list(User.objects.filter(pk__in=ids, is_active=True))
        added = services.add_members(channel, users)
        if added:
            log_action(request.user, AuditLog.Action.UPDATE, channel, request=request,
                       changes={"members_added": [None, _names(u for u in users if u.pk in added)]})
        return Response({"added": added})

    @extend_schema(request=None, responses={204: None})
    @action(detail=True, methods=["delete"], url_path=r"members/(?P<user_id>\d+)")
    def remove_member(self, request, pk=None, user_id=None):
        channel = self._managed_channel(request)
        if channel.is_default:
            raise ValidationError({"detail": _("Members of default channels follow the organization automatically.")})
        person = get_object_or_404(User, pk=user_id)
        if services.remove_members(channel, [person.pk]):
            log_action(request.user, AuditLog.Action.UPDATE, channel, request=request, changes={"members_removed": [person.full_name, None]})
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=None, responses={200: ConversationSerializer})
    @action(detail=True, methods=["post"])
    def join(self, request, pk=None):
        """Join a public channel."""
        channel = self.get_object()
        if not channel.is_channel or channel.is_private or channel.archived:
            raise PermissionDenied(_("You can only join open, public channels."))
        if services.add_members(channel, [request.user]):
            log_action(request.user, AuditLog.Action.UPDATE, channel, request=request, changes={"members_added": [None, request.user.full_name]})
        return Response(self._reload(channel))

    @extend_schema(request=None, responses={204: None})
    @action(detail=True, methods=["post"])
    def leave(self, request, pk=None):
        channel = self.get_object()
        if not channel.is_channel:
            raise ValidationError({"detail": _("You can't leave a direct message.")})
        if channel.is_default:
            raise ValidationError({"detail": _("Everyone stays in default channels.")})
        if services.remove_members(channel, [request.user.pk]):
            log_action(request.user, AuditLog.Action.UPDATE, channel, request=request, changes={"members_removed": [request.user.full_name, None]})
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ------------------------------------------------------------ direct messages

    @extend_schema(request=DirectSerializer, responses={200: ConversationSerializer})
    @action(detail=False, methods=["post"])
    def direct(self, request):
        """Open (or start) the direct message with a colleague: {"user": id}."""
        try:
            other = User.objects.get(pk=int(request.data.get("user")), is_active=True)
        except (TypeError, ValueError, User.DoesNotExist):
            raise ValidationError({"user": _("Choose a colleague.")})
        conversation, created = services.get_or_create_dm(request.user, other)
        return Response(self._reload(conversation), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @extend_schema(responses={200: dict})
    @action(detail=False, methods=["get"])
    def unread(self, request):
        """Unread messages across all your conversations (for the badge)."""
        return Response({"count": services.total_unread(request.user)})

    # ------------------------------------------------------------ messages

    @extend_schema(
        parameters=[OpenApiParameter("cursor", str), OpenApiParameter("page_size", int)],
        request=MessageSerializer, responses={200: MessageSerializer(many=True), 201: MessageSerializer},
    )
    @action(detail=True, methods=["get", "post"])
    def messages(self, request, pk=None):
        """GET: history, newest first (follow `next` for older).

        POST: send `body` and/or up to 5 `files` (multipart; 10 MB each, same types as task files),
        optionally `reply_to` a message in this conversation.
        """
        conversation = self.get_object()
        if request.method == "GET":
            if not rules.readable_conversations(request.user).filter(pk=conversation.pk).exists():
                raise PermissionDenied(_("Only members can read this conversation."))
            qs = services.with_details(Message.objects.filter(conversation=conversation))
            around = request.query_params.get("around")
            if around:
                # One message "in context": up to AROUND older and newer messages (newest first).
                try:
                    pivot = int(around)
                except ValueError:
                    raise ValidationError({"around": _("Give a message id.")})
                older = list(qs.filter(id__lte=pivot).order_by("-id")[: AROUND + 2])
                newer = list(qs.filter(id__gt=pivot).order_by("id")[: AROUND + 1])
                if not older or older[0].pk != pivot:
                    raise NotFound()
                return Response({
                    "results": [services.message_data(m) for m in reversed(newer[:AROUND])] + [services.message_data(m) for m in older[: AROUND + 1]],
                    "has_newer": len(newer) > AROUND,
                    "has_older": len(older) > AROUND + 1,
                })
            paginator = MessageHistoryPagination()
            page = paginator.paginate_queryset(qs, request, view=self)
            return paginator.get_paginated_response([services.message_data(m) for m in page])
        if not rules.can_post(request.user, conversation):
            raise PermissionDenied(_("Join this conversation to write in it.") if not conversation.archived else _("This channel is archived."))
        files = request.FILES.getlist("files")
        context = {**self.get_serializer_context(), "conversation": conversation, "has_files": bool(files)}
        serializer = MessageSerializer(data=request.data, context=context)
        serializer.is_valid(raise_exception=True)
        check_broadcast(request, conversation, serializer.validated_data["body"])
        message = services.send_message(
            conversation, request.user, serializer.validated_data["body"], serializer.validated_data.get("reply_to"), files
        )
        fresh = services.with_details(Message.objects.filter(pk=message.pk)).get()
        return Response(services.message_data(fresh), status=status.HTTP_201_CREATED)

    @extend_schema(parameters=[OpenApiParameter("q", str)], responses={200: dict})
    @action(detail=True, methods=["get"])
    def people(self, request, pk=None):
        """People to suggest after "@": members (anyone, for a public channel), closest matches first.
        `can_broadcast` says whether @channel and @here may be offered."""
        conversation = self.get_object()
        if not rules.readable_conversations(request.user).filter(pk=conversation.pk).exists():
            raise PermissionDenied()
        people = [p for p in mentions.suggestions(conversation, request.query_params.get("q", "")) if p.pk != request.user.pk]
        return Response({
            "people": [services.person(p) for p in people],
            "can_broadcast": mentions.can_broadcast(request.user, conversation),
        })

    @extend_schema(request=MuteSerializer, responses={200: ConversationSerializer})
    @action(detail=True, methods=["post"])
    def mute(self, request, pk=None):
        """{"muted": true|false}: no notifications or emails while muted; not counted in the badge."""
        conversation = self.get_object()
        if not rules.is_member(request.user, conversation):
            raise PermissionDenied(_("Only members can mute a conversation."))
        muted = request.data.get("muted", True)
        services.set_muted(conversation, request.user, muted not in (False, "false", "0", 0))
        return Response(self._reload(conversation))

    @extend_schema(responses={200: dict})
    @action(detail=False, methods=["get"])
    def presence(self, request):
        """Colleagues online now (people who share a conversation with you)."""
        return Response({"online": sorted(presence.online_ids(services.colleague_ids(request.user)))})

    @extend_schema(request=ReadSerializer, responses={200: dict})
    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        """Mark as read, up to `message` (default: the newest). Returns your unread count."""
        conversation = self.get_object()
        if not rules.is_member(request.user, conversation):
            return Response({"unread": 0})
        up_to = request.data.get("message")
        try:
            up_to = int(up_to) if up_to is not None else None
        except (TypeError, ValueError):
            raise ValidationError({"message": _("Give a message id.")})
        return Response({"unread": services.mark_read(conversation, request.user, up_to)})


class MessageViewSet(mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """Edit your own message within 15 minutes (marked "edited"), or delete it ("message deleted")."""

    module = "chat"
    permission_classes = [ModulePermission]
    serializer_class = MessageSerializer
    http_method_names = ["post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Message.objects.none()
        return Message.objects.filter(
            conversation__in=rules.readable_conversations(self.request.user)
        ).select_related("author", "conversation")

    def _own(self):
        message = self.get_object()
        if message.author_id != self.request.user.pk:
            raise PermissionDenied(_("You can only change your own messages."))
        if message.is_deleted:
            raise ValidationError({"detail": _("This message was deleted.")})
        if message.conversation.archived:
            raise PermissionDenied(_("This channel is archived."))
        return message

    @extend_schema(request=ReactSerializer, responses={200: dict})
    @action(detail=True, methods=["post"])
    def react(self, request, pk=None):
        """{"emoji": "👍"}: add your reaction, or remove it if you already gave it. Members only."""
        message = self.get_object()
        if message.is_deleted:
            raise ValidationError({"detail": _("This message was deleted.")})
        if not rules.can_post(request.user, message.conversation):
            raise PermissionDenied(_("Join this conversation to react."))
        on = services.toggle_reaction(message, request.user, request.data.get("emoji", ""))
        fresh = services.with_details(Message.objects.filter(pk=message.pk)).get()
        return Response({"reacted": on, "message": services.message_data(fresh)})

    def partial_update(self, request, pk=None):
        message = self._own()
        if timezone.now() > message.created_at + services.EDIT_WINDOW:
            raise PermissionDenied(_("Messages can be edited for 15 minutes after sending."))
        serializer = MessageSerializer(message, data={"body": request.data.get("body", "")}, partial=True)
        serializer.is_valid(raise_exception=True)
        if mentions.broadcast_kind(serializer.validated_data["body"], message.conversation) and not mentions.broadcast_kind(message.body, message.conversation):
            check_broadcast(request, message.conversation, serializer.validated_data["body"])
        services.edit_message(message, serializer.validated_data["body"])
        return Response(services.message_data(services.with_details(Message.objects.filter(pk=message.pk)).get()))

    def destroy(self, request, pk=None):
        services.delete_message(self._own())
        return Response(status=status.HTTP_204_NO_CONTENT)


class AttachmentFileViewSet(viewsets.GenericViewSet):
    """Download a message's file, or its image thumbnail. Only people who can read the conversation."""

    module = "chat"
    permission_classes = [ModulePermission]
    serializer_class = serializers.Serializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return MessageAttachment.objects.none()
        return MessageAttachment.objects.filter(
            message__conversation__in=rules.readable_conversations(self.request.user), message__deleted_at__isnull=True
        )

    def _serve(self, field, name, content_type, inline):
        if not field:
            raise Http404
        try:
            handle = field.open("rb")
        except FileNotFoundError:
            raise Http404
        response = FileResponse(handle, content_type=content_type, as_attachment=not inline, filename=name)
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        response["Cache-Control"] = "private, max-age=3600"
        return response

    @extend_schema(responses={(200, "application/octet-stream"): bytes})
    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        a = self.get_object()
        # Images and PDFs can open in the browser; everything else downloads.
        inline = a.kind in ("image", "pdf") and request.query_params.get("inline") == "1"
        return self._serve(a.file, a.original_name, a.content_type, inline)

    @extend_schema(responses={(200, "image/webp"): bytes})
    @action(detail=True, methods=["get"])
    def thumbnail(self, request, pk=None):
        a = self.get_object()
        return self._serve(a.thumbnail, "thumbnail.webp", "image/webp", True)


class MentionsView(APIView):
    """Messages that mention me (by name, @channel or @here), newest first, in conversations I can still read.
    `unread` counts those I haven't read yet."""

    module = "chat"
    permission_classes = [ModulePermission]

    @extend_schema(parameters=[OpenApiParameter("cursor", str)], responses={200: dict})
    def get(self, request):
        qs = services.with_details(
            Message.objects.filter(
                mention_links__user=request.user, deleted_at__isnull=True,
                conversation__in=rules.readable_conversations(request.user).filter(archived_at__isnull=True),
            ).select_related("conversation")
        )
        paginator = FoundPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        titles: dict = {}
        response = paginator.get_paginated_response([found_item(m, request.user, titles) for m in page])
        response.data["unread"] = integration.unread_mentions_count(request.user)
        return response


class MessageSearchView(APIView):
    """Search messages in conversations I can read (not archived ones). `q` (at least 2 characters),
    optional `conversation`, `author`, `date_from`, `date_to` (YYYY-MM-DD). Newest first.
    `terms` are the words to highlight."""

    module = "chat"
    permission_classes = [ModulePermission]

    @extend_schema(
        parameters=[
            OpenApiParameter("q", str, required=True), OpenApiParameter("conversation", int), OpenApiParameter("author", int),
            OpenApiParameter("date_from", str), OpenApiParameter("date_to", str), OpenApiParameter("cursor", str),
        ],
        responses={200: dict},
    )
    def get(self, request):
        from django.utils.dateparse import parse_date

        params = request.query_params
        q = params.get("q", "").strip()
        if len(q) < MIN_QUERY:
            return Response({"next": None, "previous": None, "results": [], "terms": []})

        def number(name):
            try:
                return int(params[name]) if params.get(name) else None
            except ValueError:
                raise ValidationError({name: _("Give a number.")})

        qs = search_messages(
            request.user, q, conversation=number("conversation"), author=number("author"),
            date_from=parse_date(params.get("date_from") or "") if params.get("date_from") else None,
            date_to=parse_date(params.get("date_to") or "") if params.get("date_to") else None,
        )
        qs = services.with_details(qs.select_related("conversation"))
        paginator = FoundPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        titles: dict = {}
        response = paginator.get_paginated_response([found_item(m, request.user, titles) for m in page])
        response.data["terms"] = terms(q)
        return response


class RecordCardView(APIView):
    """A small card for a link to a task, contact or company pasted in a message: `type` and `id`.
    404 unless the viewer can see that record (the message then shows a plain link)."""

    module = "chat"
    permission_classes = [ModulePermission]

    @extend_schema(parameters=[OpenApiParameter("type", str, enum=["task", "contact", "company"]), OpenApiParameter("id", int)], responses={200: dict})
    def get(self, request):
        try:
            pk = int(request.query_params.get("id", ""))
        except ValueError:
            raise NotFound()
        card = integration.record_card(request.user, request.query_params.get("type", ""), pk)
        if card is None:
            raise NotFound()
        return Response(card)
