from datetime import timedelta

from django.utils.translation import gettext as _
from rest_framework import serializers

from apps.accounts.models import Department, User
from apps.bookings.models import Resource
from apps.core.office_time import office_tz

from . import rules, services
from .models import Event


class EventSerializer(serializers.ModelSerializer):
    organizer_name = serializers.CharField(source="organizer.full_name", read_only=True, default=None)
    attendee_details = serializers.SerializerMethodField()
    department_names = serializers.SerializerMethodField()
    start_date = serializers.SerializerMethodField()
    end_date = serializers.SerializerMethodField()
    room = serializers.SerializerMethodField()
    room_name = serializers.SerializerMethodField()
    room_status = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = [
            "id", "kind", "title", "description", "location", "all_day", "start", "end", "start_date", "end_date",
            "organizer", "organizer_name", "attendees", "attendee_details", "audience", "departments", "department_names",
            "booking", "room", "room_name", "room_status", "can_edit", "created_at",
        ]
        read_only_fields = fields

    def get_attendee_details(self, obj) -> list[dict]:
        return [{"id": u.pk, "full_name": u.full_name} for u in obj.attendees.all()]

    def get_department_names(self, obj) -> list[str]:
        return [d.name for d in obj.departments.all()]

    def get_start_date(self, obj) -> str | None:
        return obj.start.astimezone(office_tz()).date().isoformat() if obj.all_day else None

    def get_end_date(self, obj) -> str | None:
        return (obj.end.astimezone(office_tz()).date() - timedelta(days=1)).isoformat() if obj.all_day else None

    def _holding(self, obj):
        return obj.booking if obj.booking_id and obj.booking.status in obj.booking.HOLDING else None

    def get_room(self, obj) -> int | None:
        b = self._holding(obj)
        return b.resource_id if b else None

    def get_room_name(self, obj) -> str | None:
        b = self._holding(obj)
        return b.resource.name if b else None

    def get_room_status(self, obj) -> str | None:
        return obj.booking.status if obj.booking_id else None

    def get_can_edit(self, obj) -> bool:
        return rules.can_manage(self.context["request"].user, obj)


class EventWriteSerializer(serializers.Serializer):
    """Timed items send start/end; all-day items (holidays always) send start_date/end_date (inclusive)."""

    kind = serializers.ChoiceField(choices=Event.Kind.choices, required=False)
    title = serializers.CharField(max_length=150)
    description = serializers.CharField(required=False, allow_blank=True, max_length=4000)
    location = serializers.CharField(required=False, allow_blank=True, max_length=150)
    all_day = serializers.BooleanField(required=False)
    start = serializers.DateTimeField(required=False)
    end = serializers.DateTimeField(required=False)
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)
    attendees = serializers.PrimaryKeyRelatedField(many=True, queryset=User.objects.filter(is_active=True), required=False)
    audience = serializers.ChoiceField(choices=Event.Audience.choices, required=False)
    departments = serializers.PrimaryKeyRelatedField(many=True, queryset=Department.objects.all(), required=False)
    room = serializers.PrimaryKeyRelatedField(queryset=Resource.objects.filter(type=Resource.Type.ROOM, is_active=True), required=False, allow_null=True)

    def validate_title(self, value):
        if not value.strip():
            raise serializers.ValidationError(_("Give it a title."))
        return value.strip()

    def validate(self, attrs):
        instance = self.context.get("instance")
        kind = attrs.get("kind", instance.kind if instance else Event.Kind.MEETING)
        if instance is not None and kind != instance.kind:
            raise serializers.ValidationError({"kind": [_("The kind can't be changed.")]})
        all_day = True if kind == Event.Kind.HOLIDAY else attrs.get("all_day", instance.all_day if instance else False)
        out = {k: v for k, v in attrs.items() if k not in ("start_date", "end_date", "start", "end")}
        out["kind"], out["all_day"] = kind, all_day
        if all_day:
            saved_first = instance.start.astimezone(office_tz()).date() if instance and instance.all_day else None
            saved_last = instance.end.astimezone(office_tz()).date() - timedelta(days=1) if instance and instance.all_day else None
            first = attrs.get("start_date") or saved_first
            # A new first day without a last day means a one-day item.
            last = attrs.get("end_date") or (first if "start_date" in attrs else saved_last) or first
            if not first:
                raise serializers.ValidationError({"start_date": [_("Choose a date.")]})
            if last < first:
                raise serializers.ValidationError({"end_date": [_("The last day can't be before the first.")]})
            if (last - first).days > 31:
                raise serializers.ValidationError({"end_date": [_("At most 31 days.")]})
            out["start"], out["end"] = services.day_bounds(first, last)
            if out.get("room"):
                raise serializers.ValidationError({"room": [_("A room is booked for a time, not a whole day.")]})
        else:
            start = attrs.get("start", instance.start if instance else None)
            end = attrs.get("end", instance.end if instance else None)
            if not start or not end:
                raise serializers.ValidationError({"start": [_("Choose a start and end time.")]})
            if end <= start:
                raise serializers.ValidationError({"end": [_("The end must be after the start.")]})
            if end - start > timedelta(hours=24):
                raise serializers.ValidationError({"end": [_("At most 24 hours; use an all-day event for longer.")]})
            out["start"], out["end"] = start, end
        if kind != Event.Kind.MEETING:
            out.pop("attendees", None)
            out.pop("room", None)
        if kind == Event.Kind.EVENT:
            audience = attrs.get("audience", instance.audience if instance else Event.Audience.EVERYONE)
            departments = attrs.get("departments", list(instance.departments.all()) if instance else [])
            if audience == Event.Audience.DEPARTMENTS and not departments:
                raise serializers.ValidationError({"departments": [_("Choose at least one department.")]})
            out["audience"], out["departments"] = audience, (departments if audience == Event.Audience.DEPARTMENTS else [])
        else:
            out["audience"], out["departments"] = Event.Audience.EVERYONE, []
        if kind == Event.Kind.MEETING and "room" in attrs and attrs["room"] is not None and attrs["room"].type != Resource.Type.ROOM:
            raise serializers.ValidationError({"room": [_("Choose a meeting room.")]})
        return out
