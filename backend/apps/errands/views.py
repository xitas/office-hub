from datetime import timedelta

from django.db.models import BooleanField, Exists, ExpressionWrapper, OuterRef, Prefetch, Q
from django.http import FileResponse, Http404
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_noop as N_
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.core.audit import log_action, snapshot
from apps.core.models import AuditLog
from apps.core.office_time import office_today
from apps.core.permissions import ModulePermission
from apps.visits.views import day_start

from . import rules, services
from .models import Errand, ErrandPhoto, ErrandUpdate
from .serializers import ErrandInputSerializer, ErrandSerializer, FinishSerializer, NoteSerializer

DONE_DAYS = 60


def record_visible(user):
    """Whether the viewer may open the errand's contact or company (vendors are open to everyone)."""
    from apps.contacts.visibility import visible_companies, visible_contacts

    return ExpressionWrapper(
        Exists(visible_contacts(user).filter(pk=OuterRef("contact_id"))) | Exists(visible_companies(user).filter(pk=OuterRef("company_id")))
        | Q(vendor__isnull=False),
        output_field=BooleanField(),
    )


@extend_schema_view(list=extend_schema(parameters=[
    OpenApiParameter("scope", str, enum=["mine", "requested", "open", "team", "done", "today"],
                     description="mine (default): errands I run that aren't finished; requested: ones I asked for; open: my "
                                 "department's waiting for someone; team: my department's (managers) or everyone's (admins) "
                                 "that aren't finished; done: finished in the last 60 days that I see; today: due today"),
    OpenApiParameter("contact", int), OpenApiParameter("company", int), OpenApiParameter("vendor", int), OpenApiParameter("task", int),
]))
class ErrandViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Errands and deliveries (courier, document pickup, delivery, bank). Cancel instead of delete."""

    module = "errands"
    permission_classes = [ModulePermission]
    serializer_class = ErrandSerializer
    pagination_class = None  # bounded below
    http_method_names = ["get", "post", "patch", "head", "options"]
    # Taking and doing an errand are checked per errand (the runner, the department), whatever the role.
    action_permissions = {"take": "view", "start": "view", "finish": "view", "cancel": "edit"}
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Errand.objects.none()
        user = self.request.user
        qs = rules.visible_errands(user).select_related(
            "contact", "company", "vendor", "assigned_to", "requested_by", "department", "task",
        ).prefetch_related(
            Prefetch("updates", queryset=ErrandUpdate.objects.select_related("by")),
            Prefetch("photos", queryset=ErrandPhoto.objects.order_by("id")),
        ).annotate(record_visible=record_visible(user))
        if self.action != "list":
            return qs
        p = self.request.query_params
        for field in ("contact", "company", "vendor", "task"):
            if (v := p.get(field)) and v.isdigit():
                return qs.filter(**{f"{field}_id": int(v)}).order_by("-created_at")[:50]
        scope = p.get("scope", "mine")
        active = qs.filter(status__in=Errand.ACTIVE)
        if scope == "requested":
            return qs.filter(requested_by=user).filter(Q(status__in=Errand.ACTIVE) | Q(updated_at__gte=timezone.now() - timedelta(days=7))).order_by("-created_at")[:100]
        if scope == "open":
            return active.filter(status=Errand.Status.OPEN).order_by("due_at", "id")[:100]
        if scope == "team":
            if not (rules.is_admin(user) or rules.is_manager(user)):
                raise PermissionDenied(_("Only managers and admins see the team's errands."))
            return active.order_by("due_at", "id")[:200]
        if scope == "done":
            since = timezone.now() - timedelta(days=DONE_DAYS)
            return qs.filter(status__in=[*Errand.FINISHED, Errand.Status.CANCELLED], updated_at__gte=since).order_by("-updated_at")[:100]
        if scope == "today":
            today = office_today()
            mine = active.filter(due_at__gte=day_start(today), due_at__lt=day_start(today + timedelta(days=1)))
            if not (rules.is_admin(user) or rules.is_manager(user)):
                mine = mine.filter(Q(assigned_to=user) | Q(requested_by=user) | Q(status=Errand.Status.OPEN))
            return mine.order_by("due_at", "id")
        return active.filter(assigned_to=user).order_by("due_at", "id")[:100]

    def _out(self, errand):
        return ErrandSerializer(self.get_queryset().get(pk=errand.pk), context=self.get_serializer_context()).data

    def _input(self, partial=False):
        data = ErrandInputSerializer(data=self.request.data, partial=partial, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        return dict(data.validated_data)

    @extend_schema(request=ErrandInputSerializer, responses={201: ErrandSerializer})
    def create(self, request):
        try:
            errand = services.create(request.user, self._input())
        except services.ErrandError as exc:
            raise ValidationError(exc.errors)
        log_action(request.user, AuditLog.Action.CREATE, errand, changes=snapshot(errand), request=request)
        return Response(self._out(errand), status=status.HTTP_201_CREATED)

    @extend_schema(request=ErrandInputSerializer, responses={200: ErrandSerializer})
    def partial_update(self, request, pk=None):
        errand = self.get_object()
        try:
            changes = services.change(request.user, errand, self._input(partial=True))
        except services.NotAllowed:
            raise PermissionDenied(_("Only whoever asked, their managers and admins change an errand that isn't finished."))
        except services.ErrandError as exc:
            raise ValidationError(exc.errors)
        if changes:
            log_action(request.user, AuditLog.Action.UPDATE, errand, changes=changes, request=request)
        return Response(self._out(errand))

    def _do(self, request, errand, do, refusal, description=""):
        old = errand.status
        try:
            do()
        except services.NotAllowed:
            raise PermissionDenied(refusal)
        except services.ErrandError as exc:
            raise ValidationError(exc.errors)
        changes = {"status": [old, errand.status]}
        if errand.reference:
            changes["reference"] = [None, errand.reference]
        log_action(request.user, AuditLog.Action.UPDATE, errand, changes=changes, request=request, description=description)
        return Response(self._out(errand))

    @extend_schema(request=None, responses={200: ErrandSerializer})
    @action(detail=True, methods=["post"])
    def take(self, request, pk=None):
        """I'll do it: take an errand waiting for someone in my department."""
        errand = self.get_object()
        return self._do(request, errand, lambda: services.take(request.user, errand), _("This errand isn't waiting for someone from your department."),
                        N_("Took the errand"))

    @extend_schema(request=None, responses={200: ErrandSerializer})
    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        """On my way."""
        errand = self.get_object()
        return self._do(request, errand, lambda: services.start(request.user, errand), _("Only the person doing it marks it on the way."))

    @extend_schema(request=FinishSerializer, responses={200: ErrandSerializer})
    @action(detail=True, methods=["post"])
    def finish(self, request, pk=None):
        """Done (note, tracking or receipt number, proof photos) or not done (why)."""
        errand = self.get_object()
        data = FinishSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        return self._do(request, errand, lambda: services.finish(request.user, errand, done=v["done"], note=v["note"], reference=v["reference"],
                                                                  files=request.FILES.getlist("photos")),
                        _("Only the person doing it, their managers and admins mark it done."))

    @extend_schema(request=NoteSerializer, responses={200: ErrandSerializer})
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        errand = self.get_object()
        data = NoteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return self._do(request, errand, lambda: services.cancel(request.user, errand, data.validated_data["note"]),
                        _("Only whoever asked, their managers and admins cancel an errand."))


class ErrandPhotoViewSet(viewsets.GenericViewSet):
    """A proof photo, or its thumbnail: only people who can see the errand."""

    module = "errands"
    permission_classes = [ModulePermission]
    serializer_class = NoteSerializer  # (no body; for the schema)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ErrandPhoto.objects.none()
        return ErrandPhoto.objects.filter(errand__in=rules.visible_errands(self.request.user))

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
        photo = self.get_object()
        return self._serve(photo.file, photo.original_name, photo.content_type, request.query_params.get("inline") == "1")

    @extend_schema(responses={(200, "image/webp"): bytes})
    @action(detail=True, methods=["get"])
    def thumbnail(self, request, pk=None):
        return self._serve(self.get_object().thumbnail, "thumbnail.webp", "image/webp", True)
