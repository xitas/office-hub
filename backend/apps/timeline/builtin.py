"""Built-in timeline types (note, call, meeting) and automatic entries (status changes, created)."""
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from .registry import EntryType, auto_entry, register_provider, register_type


class CallDetailsSerializer(serializers.Serializer):
    DIRECTIONS = [("in", _("Incoming")), ("out", _("Outgoing"))]
    OUTCOMES = [
        ("connected", _("Connected")),
        ("no_answer", _("No answer")),
        ("busy", _("Busy")),
        ("voicemail", _("Left voicemail")),
        ("wrong_number", _("Wrong number")),
    ]
    direction = serializers.ChoiceField(choices=DIRECTIONS)
    outcome = serializers.ChoiceField(choices=OUTCOMES)
    duration_minutes = serializers.IntegerField(min_value=0, max_value=600, required=False, allow_null=True)


class MeetingDetailsSerializer(serializers.Serializer):
    location = serializers.CharField(max_length=200, required=False, allow_blank=True)
    attendees = serializers.CharField(max_length=500, required=False, allow_blank=True)


register_type(EntryType("note", _("Note"), None, allows_follow_up=True))
# A call or meeting can be logged with just its details ("no answer", "met at their office").
register_type(EntryType("call", _("Call"), CallDetailsSerializer, allows_follow_up=True, requires_summary=False))
register_type(EntryType("meeting", _("Meeting"), MeetingDetailsSerializer, allows_follow_up=True, requires_summary=False))


def status_entries(user, contact_ids, company_ids):
    from apps.contacts.models import ContactStatusChange

    changes = (
        ContactStatusChange.objects.filter(contact_id__in=contact_ids)
        .exclude(from_status="")  # the initial status is shown by the "created" entry
        .select_related("contact", "changed_by")
    )
    return [
        auto_entry(
            uid=f"status:{c.pk}",
            kind="status",
            occurred_at=c.changed_at,
            summary=c.reason,
            user=c.changed_by,
            details={"from": c.from_status, "to": c.to_status},
            contact=c.contact,
        )
        for c in changes
    ]


def created_entries(user, contact_ids, company_ids):
    from apps.contacts.models import Company, Contact, ContactStatusChange

    initial = dict(
        ContactStatusChange.objects.filter(contact_id__in=contact_ids, from_status="").values_list("contact_id", "to_status")
    )
    entries = [
        auto_entry(
            uid=f"created:contact:{c.pk}",
            kind="created",
            occurred_at=c.created_at,
            summary="",
            user=c.created_by,
            details={"record": "contact", "status": initial.get(c.pk)},
            contact=c,
        )
        for c in Contact.objects.filter(pk__in=contact_ids).select_related("created_by")
    ]
    entries += [
        auto_entry(
            uid=f"created:company:{c.pk}",
            kind="created",
            occurred_at=c.created_at,
            summary="",
            user=c.created_by,
            details={"record": "company"},
            company=c,
        )
        for c in Company.objects.filter(pk__in=company_ids).select_related("created_by")
    ]
    return entries


register_provider("status", status_entries)
register_provider("created", created_entries)
