"""Checklist, comments and attachments of one task (nested under /tasks/{task_pk}/)."""
from django.db import transaction
from django.db.models import Max
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_noop
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.core.audit import log_action
from apps.core.models import AuditLog
from apps.core.permissions import ModulePermission

from .collab import (
    can_change_comment,
    can_delete_attachment,
    can_delete_comment,
    can_edit_task,
    mentioned_ids,
    notify_comment,
    people_who_can_see,
    record,
)
from .collab_serializers import AttachmentSerializer, ChecklistItemSerializer, CommentSerializer
from .files import FileRejected, check_upload, make_thumbnail
from .models import ChecklistItem, Task, TaskAttachment, TaskComment
from .rules import visible_tasks

MAX_FILES_PER_UPLOAD = 10


class TaskChildMixin:
    """Everything here belongs to a task the user can see; anything else is a 404."""

    module = "tasks"
    permission_classes = [ModulePermission]

    def get_task(self) -> Task:
        if not hasattr(self, "_task"):
            self._task = get_object_or_404(visible_tasks(self.request.user), pk=self.kwargs["task_pk"])
        return self._task

    def require_edit(self):
        if not can_edit_task(self.request.user):
            raise PermissionDenied()


# ================================================================ checklist


class ChecklistViewSet(TaskChildMixin, viewsets.GenericViewSet):
    """Checklist (subtasks). Anyone who can see the task may tick items; changing them needs task edit rights."""

    serializer_class = ChecklistItemSerializer
    pagination_class = None
    # Ticking is checked per field below; every other change needs "edit".
    action_permissions = {"list": "view", "partial_update": "view", "create": "edit", "destroy": "edit", "reorder": "edit"}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ChecklistItem.objects.none()
        return self.get_task().checklist.select_related("done_by")

    def list(self, request, task_pk=None):
        return Response(self.get_serializer(self.get_queryset(), many=True).data)

    def create(self, request, task_pk=None):
        task = self.get_task()
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        position = (task.checklist.aggregate(m=Max("position"))["m"] or 0) + 1
        item = ser.save(task=task, created_by=request.user, position=position)
        record(task, request.user, "checklist_added", text=item.text)
        return Response(self.get_serializer(item).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, task_pk=None, pk=None):
        item = get_object_or_404(self.get_queryset(), pk=pk)
        ser = self.get_serializer(item, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        changes_text = "text" in ser.validated_data and ser.validated_data["text"] != item.text
        if changes_text:
            self.require_edit()
        old_text, was_done = item.text, item.done
        if "done" in ser.validated_data and ser.validated_data["done"] != was_done:
            done = ser.validated_data["done"]
            ser.validated_data.update(done_by=request.user if done else None, done_at=timezone.now() if done else None)
        item = ser.save()
        task = self.get_task()
        if changes_text:
            record(task, request.user, "checklist_renamed", text=item.text, old=old_text)
        if item.done != was_done:
            record(task, request.user, "checklist_done" if item.done else "checklist_undone", text=item.text)
        return Response(self.get_serializer(item).data)

    def destroy(self, request, task_pk=None, pk=None):
        item = get_object_or_404(self.get_queryset(), pk=pk)
        task = self.get_task()
        log_action(
            request.user, AuditLog.Action.DELETE, item, request=request,
            changes={"task": task.title, "text": item.text, "done": item.done},
        )
        record(task, request.user, "checklist_removed", text=item.text)
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=serializers.ListSerializer(child=serializers.IntegerField()), responses=ChecklistItemSerializer(many=True))
    @action(detail=False, methods=["post"])
    def reorder(self, request, task_pk=None):
        """Body: {"order": [item ids in the new order]} (every item of the task, once)."""
        order = request.data.get("order")
        items = {i.pk: i for i in self.get_queryset()}
        if not isinstance(order, list) or sorted(order) != sorted(items) or len(set(order)) != len(order):
            raise ValidationError({"order": [_("Send every checklist item once, in the new order.")]})
        with transaction.atomic():
            for position, pk in enumerate(order, start=1):
                if items[pk].position != position:
                    ChecklistItem.objects.filter(pk=pk).update(position=position)
        return Response(self.get_serializer(self.get_queryset(), many=True).data)


# ================================================================ attachments


def save_attachments(request, task, files, comment=None) -> list[TaskAttachment]:
    """Check every file first (all or nothing), then store them with random names."""
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise ValidationError({"files": [_("Upload up to %(n)s files at a time.") % {"n": MAX_FILES_PER_UPLOAD}]})
    checked = []
    for upload in files:
        try:
            checked.append((upload, check_upload(upload)))
        except FileRejected as exc:
            raise ValidationError({"files": [str(exc)]})
    saved = []
    for upload, info in checked:
        attachment = TaskAttachment(
            task=task, comment=comment, original_name=upload.name[:255], size=upload.size,
            content_type=info.content_type, kind=info.kind, uploaded_by=request.user,
        )
        thumb = make_thumbnail(upload) if info.kind == TaskAttachment.Kind.IMAGE else None
        attachment.file.save(f"upload.{info.extension}", upload, save=False)
        if thumb:
            attachment.thumbnail.save("thumb.webp", thumb, save=False)
        attachment.save()
        saved.append(attachment)
        log_action(
            request.user, AuditLog.Action.CREATE, attachment, request=request,
            changes={"task": task.title, "file": attachment.original_name, "size": attachment.size, "kind": attachment.kind},
            description=gettext_noop("Attached a file to a task"),
        )
        if comment is None:
            record(task, request.user, "attachment_added", name=attachment.original_name)
    return saved


class TaskAttachmentViewSet(TaskChildMixin, viewsets.GenericViewSet):
    """Files on a task (up to 10 MB each; PDF, images, Office, text/CSV, ZIP — checked by content)."""

    serializer_class = AttachmentSerializer
    pagination_class = None
    parser_classes = [MultiPartParser, FormParser]
    action_permissions = {"list": "view", "create": "edit"}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return TaskAttachment.objects.none()
        return self.get_task().attachments.select_related("uploaded_by")

    def list(self, request, task_pk=None):
        return Response(self.get_serializer(self.get_queryset(), many=True).data)

    @extend_schema(request={"multipart/form-data": {"type": "object", "properties": {"files": {"type": "array", "items": {"type": "string", "format": "binary"}}}}})
    def create(self, request, task_pk=None):
        files = request.FILES.getlist("files") or request.FILES.getlist("file")
        if not files:
            raise ValidationError({"files": [_("Choose a file to upload.")]})
        saved = save_attachments(request, self.get_task(), files)
        return Response(self.get_serializer(saved, many=True).data, status=status.HTTP_201_CREATED)


class AttachmentFileViewSet(mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """Download, thumbnail and delete one attachment. The task must be visible to the user."""

    module = "tasks"
    permission_classes = [ModulePermission]
    serializer_class = AttachmentSerializer
    action_permissions = {"download": "view", "thumbnail": "view", "destroy": "edit"}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return TaskAttachment.objects.none()
        return TaskAttachment.objects.filter(task__in=visible_tasks(self.request.user)).select_related("task")

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
        inline = a.kind in (TaskAttachment.Kind.IMAGE, TaskAttachment.Kind.PDF) and request.query_params.get("inline") == "1"
        return self._serve(a.file, a.original_name, a.content_type, inline)

    @extend_schema(responses={(200, "image/webp"): bytes})
    @action(detail=True, methods=["get"])
    def thumbnail(self, request, pk=None):
        a = self.get_object()
        return self._serve(a.thumbnail, "thumbnail.webp", "image/webp", True)

    def perform_destroy(self, instance):
        if not can_delete_attachment(self.request.user, instance):
            raise PermissionDenied(_("Only the person who uploaded a file, a manager or an admin can delete it."))
        log_action(
            self.request.user, AuditLog.Action.DELETE, instance, request=self.request,
            changes={"task": instance.task.title, "file": instance.original_name, "size": instance.size},
            description=gettext_noop("Deleted a file from a task"),
        )
        if instance.comment_id is None:
            record(instance.task, self.request.user, "attachment_removed", name=instance.original_name)
        instance.delete()


# ================================================================ comments


class TaskCommentViewSet(TaskChildMixin, viewsets.GenericViewSet):
    """Comments (oldest first). Anyone who can see the task may comment; authors edit their own;
    authors, managers and admins may delete. @mentions notify people who can see the task."""

    serializer_class = CommentSerializer
    pagination_class = None
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    action_permissions = {"list": "view", "create": "view", "partial_update": "view", "destroy": "view"}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return TaskComment.objects.none()
        return self.get_task().comments.select_related("author").prefetch_related("attachments__uploaded_by")

    def _set_mentions(self, comment):
        ids = mentioned_ids(comment.body)
        allowed = people_who_can_see(comment.task).filter(pk__in=ids) if ids else []
        comment.mentions.set(allowed)

    def list(self, request, task_pk=None):
        return Response(self.get_serializer(self.get_queryset(), many=True).data)

    def create(self, request, task_pk=None):
        task = self.get_task()
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        files = request.FILES.getlist("files")
        if not ser.validated_data.get("body") and not files:
            raise ValidationError({"body": [_("Write a comment or attach a file.")]})
        with transaction.atomic():
            comment = ser.save(task=task, author=request.user)
            if files:
                save_attachments(request, task, files, comment=comment)
            self._set_mentions(comment)
        notify_comment(comment, request.user)
        return Response(self.get_serializer(comment).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, task_pk=None, pk=None):
        comment = get_object_or_404(self.get_queryset(), pk=pk)
        if not can_change_comment(request.user, comment):
            raise PermissionDenied(_("You can only edit your own comments."))
        before = set(comment.mentions.values_list("pk", flat=True))
        ser = self.get_serializer(comment, data={"body": request.data.get("body", "")}, partial=True)
        ser.is_valid(raise_exception=True)
        if not ser.validated_data.get("body") and not comment.attachments.exists():
            raise ValidationError({"body": [_("Write a comment or attach a file.")]})
        if ser.validated_data.get("body") != comment.body:
            comment = ser.save(edited_at=timezone.now())
            self._set_mentions(comment)
            added = comment.mentions.exclude(pk__in=before).exclude(pk=request.user.pk)
            if added.exists():
                # Only people newly mentioned by the edit are told.
                from apps.notifications.models import NotificationType
                from apps.notifications.services import notify

                notify(
                    list(added), NotificationType.MENTION, link=f"/tasks/{comment.task_id}#comment-{comment.pk}",
                    actor=request.user, message="task_mention",
                    params={"actor": request.user.full_name, "task": comment.task.title, "task_id": comment.task_id},
                )
        return Response(self.get_serializer(comment).data)

    def destroy(self, request, task_pk=None, pk=None):
        comment = get_object_or_404(self.get_queryset(), pk=pk)
        if not can_delete_comment(request.user, comment):
            raise PermissionDenied(_("You can only delete your own comments."))
        log_action(
            request.user, AuditLog.Action.DELETE, comment, request=request,
            changes={"task": comment.task.title, "author": comment.author.full_name if comment.author else None,
                     "body": comment.body[:500], "files": [a.original_name for a in comment.attachments.all()]},
            description=gettext_noop("Deleted a task comment"),
        )
        for attachment in comment.attachments.all():
            attachment.delete()  # removes the stored files too
        comment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
