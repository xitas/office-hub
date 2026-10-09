from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.contacts.visibility import visible_companies, visible_contacts
from apps.core.audit import AuditedViewSetMixin
from apps.core.permissions import ModulePermission

from . import registry
from .models import TimelineEntry
from .serializers import TimelineEntrySerializer, can_modify, entry_data


def visible_entries(user):
    """Stored entries on contacts/companies the user can see."""
    return TimelineEntry.objects.filter(
        Q(contact__in=visible_contacts(user)) | Q(company__in=visible_companies(user))
    ).select_related("contact", "company", "created_by")


class TimelineViewSet(
    AuditedViewSetMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    """Interaction timeline of one contact or company.

    The list merges stored entries (notes, calls, meetings, ...) with automatic ones (status
    changes, record created) from registered providers, newest first. A company's timeline also
    includes the entries of its contacts that the user can see.

    Anyone who can see a record can add entries to it. Editing and deleting an entry is limited to
    its author, a manager of the author's department, and admins.
    """

    module = "contacts"
    permission_classes = [ModulePermission]
    serializer_class = TimelineEntrySerializer
    # Deleting your own note is an edit of the record's history, not deleting a contact.
    action_permissions = {"destroy": "edit"}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # OpenAPI schema generation
            return TimelineEntry.objects.none()
        return visible_entries(self.request.user)

    def get_object(self):
        entry = super().get_object()
        if self.action in ("update", "partial_update", "destroy") and not can_modify(self.request.user, entry):
            raise PermissionDenied(_("Only the author, their manager or an admin can change this entry."))
        return entry

    @extend_schema(
        parameters=[
            OpenApiParameter("contact", int),
            OpenApiParameter("company", int),
            OpenApiParameter("type", str, description="Comma-separated kinds, e.g. note,call"),
            OpenApiParameter("page", int),
        ],
        responses={200: dict},
    )
    def list(self, request):
        user = request.user
        params = request.query_params
        contact_id, company_id = params.get("contact"), params.get("company")
        if bool(contact_id) == bool(company_id):
            raise ValidationError({"detail": _("Pass either contact or company.")})
        try:
            if contact_id:
                contact = get_object_or_404(visible_contacts(user), pk=int(contact_id))
                contact_ids, company_ids = [contact.pk], []
            else:
                company = get_object_or_404(visible_companies(user), pk=int(company_id))
                contact_ids = list(visible_contacts(user).filter(company=company).values_list("pk", flat=True))
                company_ids = [company.pk]
        except ValueError:
            raise ValidationError({"detail": _("Invalid id.")})

        kinds = {k for k in params.get("type", "").split(",") if k}
        stored = TimelineEntry.objects.filter(
            Q(contact_id__in=contact_ids) | Q(company_id__in=company_ids)
        ).select_related("contact", "company", "created_by__department")
        if kinds:
            stored = stored.filter(kind__in=kinds)
        entries = [entry_data(e, user) for e in stored]
        for kind, provider in registry.providers().items():
            if not kinds or kind in kinds:
                entries += provider(user, contact_ids, company_ids)
        entries.sort(key=lambda e: (e["occurred_at"], e["created_at"]), reverse=True)

        page = self.paginate_queryset(entries)
        return self.get_paginated_response(page)
