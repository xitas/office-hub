from rest_framework import serializers

from apps.accounts.models import User
from apps.contacts.models import Company, Contact
from apps.contacts.visibility import visible_companies, visible_contacts
from apps.tasks.models import Task
from apps.vendors.models import Vendor

from . import rules
from .models import Visit, VisitCheck


def _spot(lat, lng, accuracy, visit) -> dict | None:
    """Coordinates, accuracy and the distance from the visit's pin (when both exist): information only."""
    if lat is None:
        return None
    from .checks import distance_m

    far = distance_m(lat, lng, visit.latitude, visit.longitude) if visit.latitude is not None else None
    return {"latitude": str(lat), "longitude": str(lng), "accuracy": accuracy, "distance_m": far}


def check_data(c, viewer, visit) -> dict:
    """One person's check-in. Coordinates only for the person, their department's managers and admins."""
    allowed = rules.can_see_location(viewer, c.user)
    return {
        "user": c.user_id, "user_name": c.user.full_name, "checked_in_at": c.checked_in_at, "checked_out_at": c.checked_out_at,
        "in_location": c.in_location, "out_location": c.out_location, "location_removed": c.location_removed_at is not None,
        "location_visible": allowed,
        "in": _spot(c.in_latitude, c.in_longitude, c.in_accuracy, visit) if allowed else None,
        "out": _spot(c.out_latitude, c.out_longitude, c.out_accuracy, visit) if allowed else None,
    }


def _ref(obj, name) -> dict | None:
    return {"id": obj.pk, "name": name} if obj else None


class VisitSerializer(serializers.ModelSerializer):
    contact = serializers.SerializerMethodField()
    company = serializers.SerializerMethodField()
    vendor = serializers.SerializerMethodField()
    place = serializers.CharField(read_only=True)
    assigned_to_name = serializers.CharField(source="assigned_to.full_name", read_only=True)
    department_name = serializers.CharField(source="assigned_to.department.name", read_only=True, default=None)
    companions = serializers.SerializerMethodField()
    task = serializers.SerializerMethodField()
    decided_by_name = serializers.CharField(source="decided_by.full_name", read_only=True, default=None)
    closed_by_name = serializers.CharField(source="closed_by.full_name", read_only=True, default=None)
    created_by_name = serializers.CharField(source="created_by.full_name", read_only=True, default=None)
    record_visible = serializers.BooleanField(read_only=True, default=True)
    checks = serializers.SerializerMethodField()
    can_check_in = serializers.SerializerMethodField()
    can_change = serializers.SerializerMethodField()
    can_close = serializers.SerializerMethodField()
    can_decide = serializers.SerializerMethodField()

    class Meta:
        model = Visit
        fields = [
            "id", "title", "purpose", "contact", "company", "vendor", "place", "place_name", "address", "city", "latitude",
            "longitude", "start", "end", "assigned_to", "assigned_to_name", "department_name", "companions", "notes", "task",
            "status", "decided_by_name", "decided_at", "decision_note", "closed_by_name", "closed_at", "close_note",
            "created_by_name", "record_visible", "checks", "can_check_in", "can_change", "can_close", "can_decide", "created_at",
        ]
        read_only_fields = fields

    def _user(self):
        return self.context["request"].user

    def get_contact(self, obj) -> dict | None:
        return _ref(obj.contact, obj.contact.full_name if obj.contact else "")

    def get_company(self, obj) -> dict | None:
        return _ref(obj.company, obj.company.name if obj.company else "")

    def get_vendor(self, obj) -> dict | None:
        return _ref(obj.vendor, obj.vendor.name if obj.vendor else "")

    def get_companions(self, obj) -> list[dict]:
        return [{"id": u.pk, "name": u.full_name} for u in obj.companions.all()]

    def get_task(self, obj) -> dict | None:
        return {"id": obj.task.pk, "title": obj.task.title, "status": obj.task.status} if obj.task else None

    def get_checks(self, obj) -> list[dict]:
        return [check_data(c, self._user(), obj) for c in obj.checks.all()]

    def get_can_check_in(self, obj) -> bool:
        me = self._user()
        return rules.can_check_in(me, obj) and not any(c.user_id == me.pk for c in obj.checks.all())

    def get_can_change(self, obj) -> bool:
        return rules.can_change(self._user(), obj)

    def get_can_close(self, obj) -> bool:
        return rules.can_close(self._user(), obj)

    def get_can_decide(self, obj) -> bool:
        return rules.can_decide(self._user(), obj)


class VisitInputSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=150)
    purpose = serializers.ChoiceField(choices=Visit.Purpose.choices, default=Visit.Purpose.MEETING)
    contact = serializers.PrimaryKeyRelatedField(queryset=Contact.objects.none(), required=False, allow_null=True)
    company = serializers.PrimaryKeyRelatedField(queryset=Company.objects.none(), required=False, allow_null=True)
    vendor = serializers.PrimaryKeyRelatedField(queryset=Vendor.objects.filter(is_active=True), required=False, allow_null=True)
    place_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    address = serializers.CharField(max_length=255, required=False, allow_blank=True)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-90, max_value=90, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-180, max_value=180, required=False, allow_null=True)
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    assigned_to = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(is_active=True), required=False)
    companions = serializers.PrimaryKeyRelatedField(many=True, queryset=User.objects.filter(is_active=True), required=False)
    notes = serializers.CharField(max_length=4000, required=False, allow_blank=True)
    task = serializers.PrimaryKeyRelatedField(queryset=Task.objects.none(), required=False, allow_null=True)

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        if request is not None and request.user.is_authenticated:
            from apps.tasks.rules import visible_tasks

            # Only records and tasks this person can see; anything else looks like an unknown id.
            fields["contact"].queryset = visible_contacts(request.user)
            fields["company"].queryset = visible_companies(request.user)
            fields["task"].queryset = visible_tasks(request.user)
        return fields

    def validate_title(self, value):
        if not value.strip():
            raise serializers.ValidationError(serializers.CharField.default_error_messages["blank"])
        return value.strip()


class VisitDecisionSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    note = serializers.CharField(required=False, allow_blank=True, max_length=300, default="")


class VisitCloseSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=300, default="")


class CheckSerializer(serializers.Serializer):
    """Where the person was when checking in or out: recorded (with coordinates), declined or unavailable."""

    location = serializers.ChoiceField(choices=VisitCheck.Location.choices)
    latitude = serializers.DecimalField(max_digits=12, decimal_places=8, min_value=-90, max_value=90, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=12, decimal_places=8, min_value=-180, max_value=180, required=False, allow_null=True)
    accuracy = serializers.FloatField(min_value=0, max_value=100_000, required=False, allow_null=True)
