from django.db.models import Prefetch
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.core.audit import diff, log_action, snapshot
from apps.core.models import AuditLog
from apps.core.office_time import office_today
from apps.core.permissions import ModulePermission, module_permission

from . import feed, rules, services
from .models import Event
from .serializers import EventSerializer, EventWriteSerializer


def _audit_snapshot(event) -> dict:
    data = snapshot(event)
    data.pop("reminded_start", None)
    data["attendees"] = sorted(u.full_name for u in event.attendees.all())
    data["departments"] = sorted(d.name for d in event.departments.all())
    return data


class EventViewSet(mixins.RetrieveModelMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """Meetings (anyone), office events (managers for their department, admins) and holidays (admins).
    The calendar lists them through /calendar/; a meeting can book a room (`room`)."""

    module = "calendar"
    permission_classes = [ModulePermission]
    serializer_class = EventSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Event.objects.none()
        return (
            rules.visible_events(self.request.user)
            .select_related("organizer", "booking__resource")
            .prefetch_related(Prefetch("attendees", queryset=User.objects.order_by("full_name")), "departments")
        )

    def _input(self, instance=None):
        data = EventWriteSerializer(data=self.request.data, partial=instance is not None, context={"instance": instance})
        data.is_valid(raise_exception=True)
        return data.validated_data

    def _out(self, event, code=status.HTTP_200_OK):
        return Response(EventSerializer(self.get_queryset().get(pk=event.pk), context=self.get_serializer_context()).data, status=code)

    @extend_schema(request=EventWriteSerializer, responses={201: EventSerializer})
    def create(self, request, *args, **kwargs):
        values = self._input()
        if not rules.can_add(request.user, values["kind"], values["audience"], {d.pk for d in values["departments"]}):
            raise PermissionDenied(_("You can't add this to the calendar.") if values["kind"] != Event.Kind.EVENT
                                   else _("Managers add events for their own department; admins for anyone."))
        try:
            event = services.create(request.user, dict(values))
        except services.CalendarError as exc:
            raise ValidationError(exc.errors)
        log_action(request.user, AuditLog.Action.CREATE, event, changes=_audit_snapshot(event), request=request)
        return self._out(event, status.HTTP_201_CREATED)

    def _managed(self):
        event = self.get_object()
        if not rules.can_manage(self.request.user, event):
            raise PermissionDenied(_("Only the organizer or an admin can change this."))
        return event

    @extend_schema(request=EventWriteSerializer, responses={200: EventSerializer})
    def partial_update(self, request, *args, **kwargs):
        event = self._managed()
        values = self._input(event)
        if event.kind == Event.Kind.EVENT and not rules.can_add(request.user, event.kind, values["audience"], {d.pk for d in values["departments"]}):
            raise PermissionDenied(_("Managers add events for their own department; admins for anyone."))
        before = _audit_snapshot(event)
        try:
            services.change(request.user, event, dict(values), room_given="room" in request.data)
        except services.CalendarError as exc:
            raise ValidationError(exc.errors)
        event = self.get_queryset().get(pk=event.pk)
        changes = diff(before, _audit_snapshot(event))
        if changes:
            log_action(request.user, AuditLog.Action.UPDATE, event, changes=changes, request=request)
        return self._out(event)

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        event = self._managed()
        log_action(request.user, AuditLog.Action.DELETE, event, changes=_audit_snapshot(event), request=request)
        services.remove(request.user, event)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CalendarView(APIView):
    """Everything on my calendar between two office days: meetings, office events, holidays, my task
    deadlines and my bookings (choose with `layers`)."""

    permission_classes = [module_permission("calendar", "view")]

    @extend_schema(parameters=[
        OpenApiParameter("from", str, required=True, description="First day, YYYY-MM-DD (office time)"),
        OpenApiParameter("to", str, required=True, description=f"Last day, at most {feed.MAX_DAYS} days later"),
        OpenApiParameter("layers", str, description="Comma-separated: " + ", ".join(feed.LAYERS)),
    ], responses={200: dict})
    def get(self, request):
        first, last = parse_date(request.query_params.get("from") or ""), parse_date(request.query_params.get("to") or "")
        if not first or not last or last < first or (last - first).days > feed.MAX_DAYS:
            raise ValidationError({"from": [_("Give a date range (from, to) of at most %(n)s days.") % {"n": feed.MAX_DAYS}]})
        layers = [x for x in (request.query_params.get("layers") or ",".join(feed.LAYERS)).split(",") if x in feed.LAYERS]
        today = office_today()
        return Response({"today": today.isoformat(), "items": feed.calendar_items(request.user, first, last, layers, today)})
