from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.http import FileResponse, Http404
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.core.audit import AuditedViewSetMixin, diff, log_action, snapshot
from apps.core.models import AuditLog
from apps.core.office_time import office_today
from apps.core.permissions import ModulePermission

from . import rules, services
from .models import Announcement, AnnouncementAttachment, AnnouncementRead
from .serializers import AnnouncementSerializer


@extend_schema_view(
    list=extend_schema(parameters=[
        OpenApiParameter("archive", bool, description="Expired announcements instead of current ones"),
        OpenApiParameter("q", str, description="Title or text"),
        OpenApiParameter("unread", bool, description="Only announcements I haven't opened"),
    ])
)
class AnnouncementViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    """The announcements board: pinned first, then newest. Expired ones are in the archive (?archive=1).

    Files are sent as multipart ``files`` on create or update; ``remove_attachments`` lists file ids to drop.
    """

    module = "announcements"
    permission_classes = [ModulePermission]
    serializer_class = AnnouncementSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    action_permissions = {"read": "view", "receipts": "view"}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Announcement.objects.none()
        user = self.request.user
        qs = (
            rules.visible_announcements(user)
            .select_related("created_by")
            .prefetch_related("departments", "attachments")
            .annotate(read_by_me=Exists(AnnouncementRead.objects.filter(announcement=OuterRef("pk"), user=user)))
        )
        if self.action != "list":
            return qs
        params = self.request.query_params
        today = office_today()
        qs = rules.expired(qs, today) if params.get("archive") in ("1", "true") else rules.current(qs, today)
        if q := params.get("q", "").strip():
            qs = qs.filter(Q(title__icontains=q) | Q(body__icontains=q))
        if params.get("unread") in ("1", "true"):
            qs = qs.filter(read_by_me=False)
        if params.get("archive") in ("1", "true"):
            return qs.order_by("-published_at", "-id")
        return qs.order_by("-pinned", "-published_at", "-id")

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "today": office_today()}

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        managed = [a for a in page if rules.can_manage(request.user, a)]
        context = {**self.get_serializer_context(), "receipts": services.receipt_counts(managed)}
        return self.get_paginated_response(AnnouncementSerializer(page, many=True, context=context).data)

    def audit_snapshot(self, instance):
        data = snapshot(instance)
        data["departments"] = sorted(d.name for d in instance.departments.all())
        data["attachments"] = [a.original_name for a in instance.attachments.all()]
        return data

    def _reload(self, instance):
        return self.get_queryset().get(pk=instance.pk)

    def create(self, request, *args, **kwargs):
        if not rules.can_post(request.user):
            raise PermissionDenied(_("Only managers with a department and admins can post announcements."))
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.validated_data.pop("remove_attachments", None)
        with transaction.atomic():  # a refused file leaves no announcement behind
            announcement = serializer.save(created_by=request.user)
            services.save_attachments(announcement, request.user, request.FILES.getlist("files"))
            log_action(request.user, AuditLog.Action.CREATE, announcement, changes=self.audit_snapshot(announcement), request=request)
            services.publish(announcement, request.user)
        return Response(self.get_serializer(self._reload(announcement)).data, status=201)

    def _managed(self):
        announcement = self.get_object()
        if not rules.can_manage(self.request.user, announcement):
            raise PermissionDenied(_("Only the author or an admin can change this announcement."))
        return announcement

    def partial_update(self, request, *args, **kwargs):
        announcement = self._managed()
        serializer = self.get_serializer(announcement, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        remove = set(serializer.validated_data.pop("remove_attachments", None) or [])
        with transaction.atomic():
            before = self.audit_snapshot(announcement)
            for attachment in announcement.attachments.filter(pk__in=remove):
                attachment.delete()  # the post_delete signal removes the files
            keep = announcement.attachments.count()
            serializer.save()
            services.save_attachments(announcement, request.user, request.FILES.getlist("files"), keep=keep)
            fresh = self._reload(announcement)
            changes = diff(before, self.audit_snapshot(fresh))
            if changes:
                log_action(request.user, AuditLog.Action.UPDATE, fresh, changes=changes, request=request)
        return Response(self.get_serializer(fresh).data)

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        self.perform_destroy(self._managed())
        return Response(status=204)

    @extend_schema(request=None, responses={200: dict})
    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        """Record that I opened it (only the first time counts)."""
        read = services.mark_read(self.get_object(), request.user)
        return Response({"read_at": read.read_at})

    @extend_schema(responses={200: dict})
    @action(detail=True, methods=["get"])
    def receipts(self, request, pk=None):
        """Who in the audience has and hasn't read it (author and admins only)."""
        announcement = self.get_object()
        if not rules.can_manage(request.user, announcement):
            raise PermissionDenied(_("Only the author or an admin can see who has read this."))
        return Response(services.receipts(announcement))


class AnnouncementFileViewSet(viewsets.GenericViewSet):
    """Download an announcement's file, or its image thumbnail. Only people who can see the announcement."""

    module = "announcements"
    permission_classes = [ModulePermission]
    serializer_class = serializers.Serializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AnnouncementAttachment.objects.none()
        return AnnouncementAttachment.objects.filter(announcement__in=rules.visible_announcements(self.request.user))

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
        return self._serve(self.get_object().thumbnail, "thumbnail.webp", "image/webp", True)
