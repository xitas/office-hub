from django.urls import reverse
from rest_framework import serializers

from apps.accounts.models import User
from apps.contacts.models import Company, Contact
from apps.contacts.visibility import visible_companies, visible_contacts
from apps.core.geo import serializer_fields
from apps.tasks.models import Task
from apps.vendors.models import Vendor

from . import rules
from .models import Errand


def _ref(obj, name) -> dict | None:
    return {"id": obj.pk, "name": name} if obj else None


def photo_data(p) -> dict:
    return {
        "id": p.pk, "original_name": p.original_name, "size": p.size, "width": p.width, "height": p.height,
        # Relative API paths: the frontend fetches them with the user's token (they are not public links).
        "download_url": reverse("errand-photo-download", args=[p.pk]).removeprefix("/api/v1"),
        "thumbnail_url": reverse("errand-photo-thumbnail", args=[p.pk]).removeprefix("/api/v1") if p.thumbnail else None,
    }


class ErrandSerializer(serializers.ModelSerializer):
    contact = serializers.SerializerMethodField()
    company = serializers.SerializerMethodField()
    vendor = serializers.SerializerMethodField()
    place = serializers.CharField(read_only=True)
    assigned_to_name = serializers.CharField(source="assigned_to.full_name", read_only=True, default=None)
    requested_by_name = serializers.CharField(source="requested_by.full_name", read_only=True, default=None)
    department_name = serializers.CharField(source="department.name", read_only=True, default=None)
    task = serializers.SerializerMethodField()
    record_visible = serializers.BooleanField(read_only=True, default=True)
    updates = serializers.SerializerMethodField()
    photos = serializers.SerializerMethodField()
    can_change = serializers.SerializerMethodField()
    can_take = serializers.SerializerMethodField()
    can_progress = serializers.SerializerMethodField()

    class Meta:
        model = Errand
        fields = [
            "id", "title", "kind", "details", "contact", "company", "vendor", "place", "place_name", "address", "city",
            "latitude", "longitude", "due_at", "assigned_to", "assigned_to_name", "requested_by", "requested_by_name",
            "department_name", "task", "status", "reference", "outcome_note", "started_at", "finished_at", "record_visible",
            "updates", "photos", "can_change", "can_take", "can_progress", "created_at",
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

    def get_task(self, obj) -> dict | None:
        return {"id": obj.task.pk, "title": obj.task.title, "status": obj.task.status} if obj.task else None

    def get_updates(self, obj) -> list[dict]:
        return [{"status": u.status, "note": u.note, "by": u.by.full_name if u.by else None, "at": u.at} for u in obj.updates.all()]

    def get_photos(self, obj) -> list[dict]:
        return [photo_data(p) for p in obj.photos.all()]

    def get_can_change(self, obj) -> bool:
        return rules.can_change(self._user(), obj)

    def get_can_take(self, obj) -> bool:
        return rules.can_take(self._user(), obj)

    def get_can_progress(self, obj) -> bool:
        return rules.can_progress(self._user(), obj)


class ErrandInputSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=150)
    kind = serializers.ChoiceField(choices=Errand.Kind.choices, default=Errand.Kind.OTHER)
    details = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    contact = serializers.PrimaryKeyRelatedField(queryset=Contact.objects.none(), required=False, allow_null=True)
    company = serializers.PrimaryKeyRelatedField(queryset=Company.objects.none(), required=False, allow_null=True)
    vendor = serializers.PrimaryKeyRelatedField(queryset=Vendor.objects.filter(is_active=True), required=False, allow_null=True)
    place_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    address = serializers.CharField(max_length=255, required=False, allow_blank=True)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    due_at = serializers.DateTimeField(required=False, allow_null=True)
    assigned_to = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(is_active=True), required=False, allow_null=True)
    task = serializers.PrimaryKeyRelatedField(queryset=Task.objects.none(), required=False, allow_null=True)

    def get_fields(self):
        fields = {**super().get_fields(), **serializer_fields()}
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


class FinishSerializer(serializers.Serializer):
    """Done or not done (multipart for proof photos)."""

    done = serializers.BooleanField()
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")


class NoteSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
