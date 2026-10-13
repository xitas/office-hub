from django.db.models import F, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.contacts.visibility import visible_contacts
from apps.core.audit import AuditedViewSetMixin, log_action
from apps.core.models import AuditLog
from apps.core.permissions import ModulePermission

from . import placeholders, rules
from .models import MessageTemplate
from .serializers import FillSerializer, MessageTemplateSerializer, PreviewSerializer


def filled(subject: str, body: str, contact, user) -> dict:
    """Subject and body with placeholders filled, what couldn't be filled, and links to send it."""
    s = placeholders.fill(subject, contact, user)
    b = placeholders.fill(body, contact, user)
    unknown = list(dict.fromkeys(s.unknown + b.unknown))
    empty = list(dict.fromkeys(s.empty + b.empty))
    return {
        "subject": s.text,
        "body": b.text,
        "unknown": unknown,
        "empty": empty,
        "whatsapp_url": placeholders.whatsapp_link(contact.whatsapp or contact.phone, b.text) if contact else None,
        "mailto_url": placeholders.mailto_link(contact.email, s.text, b.text) if contact else None,
    }


@extend_schema_view(
    list=extend_schema(parameters=[
        OpenApiParameter("q", str, description="Name or text"),
        OpenApiParameter("category", str),
        OpenApiParameter("channel", str, description="Templates for this channel, plus those for any channel"),
        OpenApiParameter("language", str),
        OpenApiParameter("owner", str, enum=["mine", "department", "everyone"]),
        OpenApiParameter("archived", bool),
    ])
)
class MessageTemplateViewSet(
    AuditedViewSetMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Message templates: personal (anyone), shared with a department (managers) or with everyone (admins).
    Most used first. Archive instead of delete."""

    module = "templates"
    permission_classes = [ModulePermission]
    serializer_class = MessageTemplateSerializer
    pagination_class = None  # an office has a few dozen templates
    http_method_names = ["get", "post", "patch", "head", "options"]
    action_permissions = {"fill": "view", "preview": "view", "use": "view", "placeholders": "view", "duplicate": "create"}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return MessageTemplate.objects.none()
        qs = rules.visible_templates(self.request.user).select_related("created_by", "department")
        if self.action != "list":
            return qs
        params = self.request.query_params
        if params.get("archived") not in ("1", "true"):
            qs = qs.filter(archived_at__isnull=True)
        if q := params.get("q", "").strip():
            qs = qs.filter(Q(name__icontains=q) | Q(body__icontains=q) | Q(subject__icontains=q))
        for field in ("category", "language"):
            if value := params.get(field):
                qs = qs.filter(**{field: value})
        if channel := params.get("channel"):
            qs = qs.filter(channel__in=[channel, MessageTemplate.Channel.ANY])
        owner = params.get("owner")
        if owner == "mine":
            qs = qs.filter(created_by=self.request.user)
        elif owner == "department":
            qs = qs.filter(sharing=MessageTemplate.Sharing.DEPARTMENT)
        elif owner == "everyone":
            qs = qs.filter(sharing=MessageTemplate.Sharing.EVERYONE)
        return qs.order_by("-usage_count", F("last_used_at").desc(nulls_last=True), "name", "id")

    def _editable(self):
        template = self.get_object()
        if not rules.can_edit(self.request.user, template):
            raise PermissionDenied(_("You can't change this template."))
        return template

    def perform_update(self, serializer):
        if not rules.can_edit(self.request.user, serializer.instance):
            raise PermissionDenied(_("You can't change this template."))
        super().perform_update(serializer)

    @extend_schema(request=None, responses={200: MessageTemplateSerializer})
    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        template = self._editable()
        if template.archived_at is None:
            template.archived_at = timezone.now()
            template.save(update_fields=["archived_at", "updated_at"])
            log_action(request.user, AuditLog.Action.UPDATE, template, changes={"archived": [False, True]}, request=request)
        return Response(self.get_serializer(template).data)

    @extend_schema(request=None, responses={200: MessageTemplateSerializer})
    @action(detail=True, methods=["post"])
    def unarchive(self, request, pk=None):
        template = self._editable()
        if template.archived_at is not None:
            template.archived_at = None
            template.save(update_fields=["archived_at", "updated_at"])
            log_action(request.user, AuditLog.Action.UPDATE, template, changes={"archived": [True, False]}, request=request)
        return Response(self.get_serializer(template).data)

    @extend_schema(request=None, responses={201: MessageTemplateSerializer})
    @action(detail=True, methods=["post"])
    def duplicate(self, request, pk=None):
        """A personal copy ("… (copy)") anyone can adapt, whoever owns the original."""
        original = self.get_object()
        copy = MessageTemplate.objects.create(
            name=(_("%(name)s (copy)") % {"name": original.name})[:120],
            category=original.category, channel=original.channel, language=original.language,
            subject=original.subject, body=original.body, sharing=MessageTemplate.Sharing.PERSONAL, created_by=request.user,
        )
        log_action(request.user, AuditLog.Action.CREATE, copy, changes={"copied_from": original.name}, request=request)
        return Response(self.get_serializer(copy).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={200: dict})
    @action(detail=True, methods=["post"])
    def use(self, request, pk=None):
        """Count one use (sent by WhatsApp or email, inserted in chat or a log entry, or copied)."""
        template = self.get_object()
        if template.archived_at is not None:
            raise PermissionDenied(_("This template is archived."))
        MessageTemplate.objects.filter(pk=template.pk).update(usage_count=F("usage_count") + 1, last_used_at=timezone.now())
        template.refresh_from_db(fields=["usage_count", "last_used_at"])
        return Response({"usage_count": template.usage_count, "last_used_at": template.last_used_at})

    def _contact(self, contact_id):
        if contact_id is None:
            return None
        # Only contacts the user can see; anyone else looks like an unknown id.
        return get_object_or_404(visible_contacts(self.request.user).select_related("company"), pk=contact_id)

    @extend_schema(request=FillSerializer, responses={200: dict})
    @action(detail=True, methods=["post"])
    def fill(self, request, pk=None):
        """The template filled for a contact (optional) and you, with WhatsApp and email links."""
        template = self.get_object()
        data = FillSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        contact = self._contact(data.validated_data.get("contact"))
        return Response(filled(template.subject, template.body, contact, request.user))

    @extend_schema(request=PreviewSerializer, responses={200: dict})
    @action(detail=False, methods=["post"])
    def preview(self, request):
        """Fill text that isn't saved yet (the editor's preview)."""
        data = PreviewSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        contact = self._contact(data.validated_data.get("contact"))
        return Response(filled(data.validated_data["subject"], data.validated_data["body"], contact, request.user))

    @extend_schema(responses={200: dict})
    @action(detail=False, methods=["get"])
    def placeholders(self, request):
        """Placeholders the editor offers, with a label and an example."""
        return Response([{"key": p.key, "label": str(p.label), "example": p.example} for p in placeholders.PLACEHOLDERS])
