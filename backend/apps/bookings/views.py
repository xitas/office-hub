from datetime import datetime, time, timedelta

from django.db.models import Case, IntegerField, Q, Value, When
from django.http import FileResponse, Http404
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.core.audit import AuditedViewSetMixin, diff, log_action, snapshot
from apps.core.models import AuditLog
from apps.core.office_time import office_tz
from apps.core.permissions import ModulePermission
from apps.core.photos import prepare_upload
from apps.tasks.files import FileRejected

from . import rules, services
from .models import Booking, Resource
from .serializers import BookingSerializer, BookingWriteSerializer, DecisionSerializer, ResourceSerializer

MAX_RANGE_DAYS = 42


# ================================================================ resources


class ResourceViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    """Rooms, projectors, vehicles… Everyone sees the ones they may book; admins manage all (also inactive ones).
    A photo is sent as multipart ``photo`` (images only, same checks as task files)."""

    module = "resources"
    permission_classes = [ModulePermission]
    serializer_class = ResourceSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    pagination_class = None  # an office has a handful of resources
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    action_permissions = {"photo": "view"}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Resource.objects.none()
        qs = rules.visible_resources(self.request.user).prefetch_related("departments")
        if t := self.request.query_params.get("type"):
            qs = qs.filter(type=t)
        if self.request.query_params.get("active") in ("1", "true"):
            qs = qs.filter(is_active=True)
        # Rooms first, then projectors, vehicles and the rest (not alphabetical by type).
        order = Case(*[When(type=t, then=Value(i)) for i, t in enumerate(Resource.Type.values)], output_field=IntegerField())
        return qs.order_by(order, "name")

    def audit_snapshot(self, instance):
        data = snapshot(instance)
        data["departments"] = sorted(d.name for d in instance.departments.all())
        data.pop("thumbnail", None)
        return data

    def _checked_photo(self):
        """A new photo, checked and cleaned (upright, no metadata) before anything is saved; None when there is none."""
        upload = self.request.FILES.get("photo")
        if not upload:
            return None
        try:
            prepared = prepare_upload(upload)
        except FileRejected as exc:
            raise ValidationError({"photo": [str(exc)]})
        if prepared.info.kind != "image":
            raise ValidationError({"photo": [_("Choose a photo (PNG, JPEG, GIF or WebP).")]})
        return prepared

    def _store_photo(self, resource, photo):
        remove = self.request.data.get("remove_photo") in (True, "true", "1")
        if not photo and not remove:
            return
        for f in (resource.photo, resource.thumbnail):
            if f:
                f.storage.delete(f.name)
        resource.photo, resource.thumbnail = "", ""
        if photo:
            resource.photo.save(f"photo.{photo.info.extension}", photo.content, save=False)
            if photo.thumbnail:
                resource.thumbnail.save("thumb.webp", photo.thumbnail, save=False)
        resource.save(update_fields=["photo", "thumbnail", "updated_at"])

    def perform_create(self, serializer):
        photo = self._checked_photo()
        serializer.validated_data.pop("remove_photo", None)
        super().perform_create(serializer)
        self._store_photo(serializer.instance, photo)

    def perform_update(self, serializer):
        photo = self._checked_photo()
        serializer.validated_data.pop("remove_photo", None)
        super().perform_update(serializer)
        self._store_photo(serializer.instance, photo)

    def perform_destroy(self, instance):
        if instance.bookings.exists():
            raise ValidationError({"detail": _("This resource has bookings. Make it inactive instead.")})
        super().perform_destroy(instance)

    @extend_schema(responses={(200, "image/*"): bytes})
    @action(detail=True, methods=["get"])
    def photo(self, request, pk=None):
        resource = self.get_object()
        field = resource.thumbnail if request.query_params.get("size") == "thumb" else resource.photo
        if not field:
            raise Http404
        try:
            handle = field.open("rb")
        except FileNotFoundError:
            raise Http404
        ext = field.name.rsplit(".", 1)[-1].lower()
        content_type = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif"}.get(ext, "image/webp")
        response = FileResponse(handle, content_type=content_type)
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        response["Cache-Control"] = "private, max-age=3600"
        return response


# ================================================================ bookings


def _occurrence_data(o) -> dict:
    return {
        "start": o.start.isoformat(),
        "end": o.end.isoformat(),
        "problem": o.problem,
        "message": o.message,
        "conflict": {"id": o.conflict.pk, "title": o.conflict.title, "booked_by_name": o.conflict.booked_by.full_name} if o.conflict else None,
    }


def _conflict_response(exc) -> Response:
    clash = exc.booking
    data = {"detail": str(exc), "code": "conflict"}
    if clash is not None:
        data["conflict"] = {"id": clash.pk, "title": clash.title, "booked_by_name": clash.booked_by.full_name}
    return Response(data, status=status.HTTP_409_CONFLICT)


def _occurrences_response(occurrences) -> Response:
    return Response(
        {"detail": _("Some dates can't be booked."), "code": "conflict", "occurrences": [_occurrence_data(o) for o in occurrences]},
        status=status.HTTP_409_CONFLICT,
    )


@extend_schema_view(
    list=extend_schema(parameters=[
        OpenApiParameter("from", str, description="First day (YYYY-MM-DD, office time); required unless mine/approvals"),
        OpenApiParameter("to", str, description="Last day, at most 42 days after `from`"),
        OpenApiParameter("resource", int),
        OpenApiParameter("mine", bool, description="Bookings I made or was invited to"),
        OpenApiParameter("when", str, enum=["upcoming", "past"], description="With mine"),
        OpenApiParameter("approvals", bool, description="Pending requests I can approve"),
    ])
)
class BookingViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    """Bookings of the resources you can see. Cancel instead of delete; repeats are weekly series."""

    module = "bookings"
    permission_classes = [ModulePermission]
    serializer_class = BookingSerializer
    pagination_class = None  # lists are bounded: a date range of at most 6 weeks, or 200 of mine
    http_method_names = ["get", "post", "patch", "head", "options"]
    action_permissions = {"check": "view", "cancel": "edit", "decide": "approve"}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Booking.objects.none()
        user = self.request.user
        qs = Booking.objects.select_related("resource", "booked_by", "decided_by").prefetch_related("attendees")
        if self.action != "list":
            # Your own and invited bookings stay visible even if the resource is later closed to you.
            return qs.filter(Q(resource__in=rules.visible_resources(user)) | Q(booked_by=user) | Q(attendees=user)).distinct()
        params = self.request.query_params
        now = timezone.now()
        if params.get("approvals") in ("1", "true"):
            return qs.filter(pk__in=rules.decidable_bookings(user).values("pk"), end__gt=now).order_by("start")
        if params.get("mine") in ("1", "true"):
            mine = Booking.objects.filter(Q(booked_by=user) | Q(attendees=user)).values("pk")
            qs = qs.filter(pk__in=mine)
            if params.get("when") == "past":
                return qs.filter(end__lte=now).order_by("-start")[:100]
            return qs.filter(end__gt=now).order_by("start")[:200]
        first, last = parse_date(params.get("from") or ""), parse_date(params.get("to") or "")
        if not first or not last or last < first or (last - first).days > MAX_RANGE_DAYS:
            raise ValidationError({"from": [_("Give a date range (from, to) of at most %(n)s days.") % {"n": MAX_RANGE_DAYS}]})
        tz = office_tz()
        start = datetime.combine(first, time.min, tzinfo=tz)
        end = datetime.combine(last + timedelta(days=1), time.min, tzinfo=tz)
        qs = qs.filter(resource__in=rules.visible_resources(user), start__lt=end, end__gt=start, status__in=Booking.HOLDING)
        if resource := params.get("resource"):
            qs = qs.filter(resource_id=resource)
        return qs.order_by("start", "id")

    # ------------------------------------------------------------ input

    def _input(self, partial=False):
        data = BookingWriteSerializer(data=self.request.data, partial=partial)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        resource = values.get("resource")
        if resource is not None and not rules.can_book(self.request.user, resource):
            raise ValidationError({"resource": [_("You can't book this resource.")]})
        return values

    def _created(self, bookings, skipped):
        log_action(
            self.request.user, AuditLog.Action.CREATE, bookings[0],
            changes={**snapshot(bookings[0]), "dates": len(bookings)}, request=self.request,
        )
        ctx = self.get_serializer_context()
        return Response(
            {"bookings": BookingSerializer(bookings, many=True, context=ctx).data, "skipped": [_occurrence_data(o) for o in skipped]},
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=BookingWriteSerializer, responses={201: dict, 409: dict})
    def create(self, request, *args, **kwargs):
        """Book once, or weekly on chosen days until a date (`repeat`). A series with clashing dates answers
        409 with every date and its problem; send again with ``skip_conflicts`` to book only the free dates."""
        values = self._input()
        if not values.get("repeat"):
            problems = services.time_problems(request.user, values["start"], values["end"])
            if problems:
                raise ValidationError(problems)
        try:
            bookings, skipped = services.create(
                request.user, values["resource"], title=values["title"], start=values["start"], end=values["end"],
                attendees=values.get("attendees", []), notes=values.get("notes", ""), repeat=values.get("repeat"),
                skip_conflicts=values.get("skip_conflicts", False),
            )
        except services.BookingConflict as exc:
            return _conflict_response(exc)
        except ValueError as exc:
            return _occurrences_response(exc.args[0])
        return self._created(bookings, skipped)

    @extend_schema(request=BookingWriteSerializer, responses={200: dict})
    @action(detail=False, methods=["post"])
    def check(self, request):
        """Which dates of a booking (or weekly series) are free, before saving."""
        values = self._input()
        repeat = values.get("repeat")
        times = (
            services.occurrence_times(values["start"], values["end"], repeat["weekdays"], repeat["until"]) if repeat
            else [(values["start"], values["end"])]
        )
        exclude = None
        if booking_id := request.data.get("booking"):
            exclude = self.get_queryset().filter(pk=booking_id).first()
        occurrences = services.check_occurrences(request.user, values["resource"], times, exclude=exclude)
        return Response({"occurrences": [_occurrence_data(o) for o in occurrences]})

    def _managed(self):
        booking = self.get_object()
        if not rules.can_manage(self.request.user, booking):
            raise PermissionDenied(_("Only the person who booked it or an admin can change this booking."))
        return booking

    @extend_schema(request=BookingWriteSerializer, responses={200: BookingSerializer, 409: dict})
    def partial_update(self, request, *args, **kwargs):
        booking = self._managed()
        values = self._input(partial=True)
        values.pop("repeat", None)
        values.pop("skip_conflicts", None)
        before = snapshot(booking)
        try:
            services.change(request.user, booking, values)
        except services.BookingConflict as exc:
            return _conflict_response(exc)
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)})
        booking = self.get_queryset().get(pk=booking.pk)
        changes = diff(before, snapshot(booking))
        if changes:
            log_action(request.user, AuditLog.Action.UPDATE, booking, changes=changes, request=request)
        return Response(BookingSerializer(booking, context=self.get_serializer_context()).data)

    @extend_schema(request={"application/json": {"type": "object", "properties": {"following": {"type": "boolean"}}}}, responses={200: dict})
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Cancel this booking, or with ``following`` this and the later dates of its series."""
        booking = self._managed()
        try:
            cancelled = services.cancel(request.user, booking, following=request.data.get("following") in (True, "true", "1"))
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)})
        for b in cancelled:
            log_action(request.user, AuditLog.Action.UPDATE, b, changes={"status": [b.status, Booking.Status.CANCELLED]}, request=request)
        return Response({"cancelled": [b.pk for b in cancelled]})

    @extend_schema(request=DecisionSerializer, responses={200: BookingSerializer})
    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        """Approve or reject a pending booking (admins, or a manager of the requester's department)."""
        booking = self.get_object()
        data = DecisionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        old = booking.status
        try:
            services.decide(request.user, booking, approve=data.validated_data["approve"], reason=data.validated_data.get("reason", ""))
        except PermissionError:
            raise PermissionDenied(_("You can't decide on this booking."))
        log_action(request.user, AuditLog.Action.UPDATE, booking, changes={"status": [old, booking.status]}, request=request)
        return Response(BookingSerializer(self.get_queryset().get(pk=booking.pk), context=self.get_serializer_context()).data)
