from django.urls import reverse
from django.utils.translation import gettext as _
from rest_framework import serializers
from rest_framework.fields import empty

from apps.accounts.models import Department, User

from . import rules
from .models import Booking, Resource


class FormBooleanField(serializers.BooleanField):
    """A yes/no that, left out of a multipart form (photo uploads), keeps its default instead of becoming False."""

    default_empty_html = empty


class ResourceSerializer(serializers.ModelSerializer):
    needs_approval = FormBooleanField(required=False, default=False)
    is_active = FormBooleanField(required=False, default=True)
    departments = serializers.PrimaryKeyRelatedField(many=True, queryset=Department.objects.all(), required=False)
    department_names = serializers.SerializerMethodField()
    photo_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    remove_photo = FormBooleanField(write_only=True, required=False)

    class Meta:
        model = Resource
        fields = [
            "id", "name", "type", "capacity", "location", "description", "bookable_by", "departments", "department_names",
            "needs_approval", "is_active", "photo_url", "thumbnail_url", "remove_photo", "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]
        extra_kwargs = {"capacity": {"min_value": 1, "max_value": 1000}}

    def get_department_names(self, obj) -> list[str]:
        return [d.name for d in obj.departments.all()]

    # Relative API paths: the frontend fetches them with the user's token (the files are private).
    def get_photo_url(self, obj) -> str | None:
        return reverse("resource-photo", args=[obj.pk]).removeprefix("/api/v1") if obj.photo else None

    def get_thumbnail_url(self, obj) -> str | None:
        return reverse("resource-photo", args=[obj.pk]).removeprefix("/api/v1") + "?size=thumb" if obj.thumbnail else None

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError(_("Give the resource a name."))
        return value.strip()

    def validate(self, attrs):
        bookable_by = attrs.get("bookable_by", getattr(self.instance, "bookable_by", Resource.BookableBy.EVERYONE))
        if bookable_by == Resource.BookableBy.EVERYONE:
            attrs["departments"] = []
        elif "departments" in attrs and not attrs["departments"]:
            raise serializers.ValidationError({"departments": [_("Choose at least one department.")]})
        elif self.instance is None and not attrs.get("departments"):
            raise serializers.ValidationError({"departments": [_("Choose at least one department.")]})
        rtype = attrs.get("type", getattr(self.instance, "type", Resource.Type.ROOM))
        if rtype != Resource.Type.ROOM:
            attrs["capacity"] = None  # capacity is for rooms
        return attrs


class PersonSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "full_name"]


class BookingSerializer(serializers.ModelSerializer):
    resource_name = serializers.CharField(source="resource.name", read_only=True)
    resource_type = serializers.CharField(source="resource.type", read_only=True)
    booked_by_name = serializers.CharField(source="booked_by.full_name", read_only=True)
    attendee_details = PersonSerializer(source="attendees", many=True, read_only=True)
    decided_by_name = serializers.CharField(source="decided_by.full_name", read_only=True, default=None)
    can_edit = serializers.SerializerMethodField()
    can_decide = serializers.SerializerMethodField()
    is_series = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            "id", "resource", "resource_name", "resource_type", "title", "start", "end", "booked_by", "booked_by_name",
            "attendees", "attendee_details", "notes", "status", "series", "is_series", "decided_by_name", "decided_at",
            "decision_reason", "can_edit", "can_decide", "created_at",
        ]
        read_only_fields = fields

    def get_can_edit(self, obj) -> bool:
        return obj.status in Booking.HOLDING and not obj.is_past and rules.can_manage(self.context["request"].user, obj)

    def get_can_decide(self, obj) -> bool:
        return rules.can_decide(self.context["request"].user, obj)

    def get_is_series(self, obj) -> bool:
        return obj.series_id is not None


class RepeatSerializer(serializers.Serializer):
    weekdays = serializers.ListField(child=serializers.IntegerField(min_value=0, max_value=6), min_length=1, max_length=7)
    until = serializers.DateField()


class BookingWriteSerializer(serializers.Serializer):
    resource = serializers.PrimaryKeyRelatedField(queryset=Resource.objects.all())
    title = serializers.CharField(max_length=150)
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    attendees = serializers.PrimaryKeyRelatedField(many=True, queryset=User.objects.filter(is_active=True), required=False)
    notes = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    repeat = RepeatSerializer(required=False, allow_null=True)
    skip_conflicts = serializers.BooleanField(required=False, default=False)

    def validate_title(self, value):
        if not value.strip():
            raise serializers.ValidationError(_("Give the booking a title."))
        return value.strip()

    def validate(self, attrs):
        repeat = attrs.get("repeat")
        if repeat and "start" in attrs and repeat["until"] <= attrs["start"].date():
            raise serializers.ValidationError({"repeat": [_("Repeat until a later date.")]})
        return attrs


class DecisionSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    reason = serializers.CharField(max_length=300, required=False, allow_blank=True)
