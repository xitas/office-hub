from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.contacts.visibility import visible_companies, visible_contacts
from apps.core.audit import AuditedViewSetMixin
from apps.core.permissions import ModulePermission, has_perm

from . import follow_ups, registry
from .log import export_log, log_queryset
from .models import TimelineEntry
from .serializers import TimelineEntrySerializer, can_modify, entry_data


def visible_entries(user):
    """Stored entries on contacts/companies the user can see, and on vendors (shared office-wide)."""
    q = Q(contact__in=visible_contacts(user)) | Q(company__in=visible_companies(user))
    if has_perm(user, "vendors", "view"):
        q |= Q(vendor__isnull=False)
    return TimelineEntry.objects.filter(q).select_related("contact", "company", "vendor", "created_by").prefetch_related(
        "follow_up_tasks__assignees"
    )


class TimelineViewSet(
    AuditedViewSetMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    """Interaction timeline of one contact, company or vendor.

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
    action_permissions = {"destroy": "edit", "log": "view", "log_export": "export"}

    def perform_create(self, serializer):
        super().perform_create(serializer)
        options = serializer.follow_up_options
        follow_ups.sync(serializer.instance, self.request.user, assignee=options["assignee"], skip=options["skip"], request=self.request)

    def perform_update(self, serializer):
        before = serializer.instance.follow_up_on
        super().perform_update(serializer)
        entry = serializer.instance
        options = serializer.follow_up_options
        follow_ups.sync(
            entry, self.request.user, assignee=options["assignee"], skip=options["skip"],
            date_changed=entry.follow_up_on != before, request=self.request,
        )

    @extend_schema(
        parameters=[
            OpenApiParameter("type", str, description="Comma-separated: note, call, meeting, email, whatsapp"),
            OpenApiParameter("direction", str, enum=["in", "out"]),
            OpenApiParameter("logged_by", int),
            OpenApiParameter("contact", int),
            OpenApiParameter("company", int, description="The company's entries and its contacts'"),
            OpenApiParameter("vendor", int),
            OpenApiParameter("date_from", str),
            OpenApiParameter("date_to", str),
            OpenApiParameter("follow_up", str, enum=["any", "open", "done", "none"]),
            OpenApiParameter("q", str),
            OpenApiParameter("page", int),
        ],
        responses={200: dict},
    )
    @action(detail=False, methods=["get"])
    def log(self, request):
        """Communication log: every call, meeting, email, WhatsApp message and note on the contacts
        and companies you can see, newest first, with filters."""
        qs = log_queryset(request.user, request.query_params).select_related("contact", "company", "vendor", "created_by__department")
        page = self.paginate_queryset(qs)
        return self.get_paginated_response([entry_data(e, request.user) for e in page])

    @extend_schema(responses={(200, "text/csv"): str})
    @action(detail=False, methods=["get"], url_path="log/export")
    def log_export(self, request):
        """The filtered log as CSV (Excel-friendly). Needs the contacts export permission."""
        return export_log(request, log_queryset(request.user, request.query_params))

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
            OpenApiParameter("vendor", int),
            OpenApiParameter("type", str, description="Comma-separated kinds, e.g. note,call"),
            OpenApiParameter("page", int),
        ],
        responses={200: dict},
    )
    def list(self, request):
        user = request.user
        params = request.query_params
        contact_id, company_id, vendor_id = params.get("contact"), params.get("company"), params.get("vendor")
        if sum(bool(x) for x in (contact_id, company_id, vendor_id)) != 1:
            raise ValidationError({"detail": _("Pass a contact, a company or a vendor.")})
        kinds = {k for k in params.get("type", "").split(",") if k}
        if vendor_id:
            return self._vendor_timeline(request, vendor_id, kinds)
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

        stored = TimelineEntry.objects.filter(
            Q(contact_id__in=contact_ids) | Q(company_id__in=company_ids)
        ).select_related("contact", "company", "created_by__department").prefetch_related("follow_up_tasks__assignees")
        if kinds:
            stored = stored.filter(kind__in=kinds)
        entries = [entry_data(e, user) for e in stored]
        for kind, provider in registry.providers().items():
            if not kinds or kind in kinds:
                entries += provider(user, contact_ids, company_ids)
        entries.sort(key=lambda e: (e["occurred_at"], e["created_at"]), reverse=True)

        page = self.paginate_queryset(entries)
        return self.get_paginated_response(page)

    def _vendor_timeline(self, request, vendor_id, kinds):
        """A vendor's logged calls, messages and notes, and automatic entries such as visits."""
        from apps.vendors.models import Vendor

        if not has_perm(request.user, "vendors", "view"):
            raise PermissionDenied
        try:
            vendor = get_object_or_404(Vendor.objects.all(), pk=int(vendor_id))
        except ValueError:
            raise ValidationError({"detail": _("Invalid id.")})
        stored = vendor.timeline_entries.select_related("vendor", "created_by__department").prefetch_related("follow_up_tasks__assignees")
        if kinds:
            stored = stored.filter(kind__in=kinds)
        entries = [entry_data(e, request.user) for e in stored]
        for kind, provider in registry.vendor_providers().items():
            if not kinds or kind in kinds:
                entries += provider(request.user, vendor.pk)
        entries.sort(key=lambda e: (e["occurred_at"], e["created_at"]), reverse=True)
        page = self.paginate_queryset(entries)
        return self.get_paginated_response(page)
