"""CSV export of contacts/companies and the CSV import API (upload → map → preview → run → results)."""
from django.http import HttpResponse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_noop
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.models import User
from apps.core.audit import log_action
from apps.core.models import AuditLog
from apps.core.permissions import ModulePermission

from .csv_io import CsvError, CsvWriter, columns_for, read_csv, suggest_mapping
from .import_messages import issue_reason
from .importer import DUPLICATE_MODES, Importer, run_import
from .models import ContactImport
from .serializers import check_assignment

# Up to this many rows run inside the request; bigger files go to a Celery worker.
SYNC_LIMIT = 300
ISSUES_IN_RESPONSE = 200


def csv_response(content: str, name: str) -> HttpResponse:
    response = HttpResponse(content, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


def _when(value) -> str:
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M") if value else ""


def export_contacts(request, queryset) -> HttpResponse:
    writer = CsvWriter(columns_for("contacts", exportable=True))
    count = 0
    for c in queryset.select_related("company", "assigned_to").prefetch_related("tags"):
        writer.row({
            "first_name": c.first_name, "last_name": c.last_name,
            "company": c.company.name if c.company else "", "job_title": c.job_title,
            "phone": c.phone, "whatsapp": c.whatsapp, "email": c.email, "address": c.address, "city": c.city,
            "tags": "; ".join(sorted((t.name for t in c.tags.all()), key=str.casefold)),
            "status": c.get_status_display(),
            "assigned_to": c.assigned_to.full_name if c.assigned_to else "",
            "created_at": _when(c.created_at),
        })
        count += 1
    _log_export(request, "contacts", count, gettext_noop("Exported contacts to a CSV file"))
    return csv_response(writer.getvalue(), f"contacts-{timezone.localdate():%Y-%m-%d}.csv")


def export_companies(request, queryset) -> HttpResponse:
    from django.db.models import Count

    writer = CsvWriter(columns_for("companies", exportable=True))
    count = 0
    for c in queryset.select_related("assigned_to").annotate(n_contacts=Count("contacts", distinct=True)):
        writer.row({
            "name": c.name, "industry": c.get_industry_display() if c.industry else "", "phone": c.phone,
            "email": c.email, "website": c.website, "address": c.address, "city": c.city, "notes": c.notes,
            "assigned_to": c.assigned_to.full_name if c.assigned_to else "",
            "contact_count": c.n_contacts, "created_at": _when(c.created_at),
        })
        count += 1
    _log_export(request, "companies", count, gettext_noop("Exported companies to a CSV file"))
    return csv_response(writer.getvalue(), f"companies-{timezone.localdate():%Y-%m-%d}.csv")


def _log_export(request, kind, count, description):
    filters = {k: v for k, v in request.query_params.items() if v and k not in ("page", "page_size")}
    log_action(
        request.user, AuditLog.Action.EXPORT, None, changes={"records": kind, "rows": count, "filters": filters},
        description=description, request=request, object_repr=f"{kind} ({count})",
    )


# ---------------------------------------------------------------- import API


class UploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    kind = serializers.ChoiceField(choices=ContactImport.Kind.choices, default=ContactImport.Kind.CONTACTS)


class ImportSettingsSerializer(serializers.Serializer):
    mapping = serializers.DictField(child=serializers.CharField(allow_blank=True))
    duplicates = serializers.ChoiceField(choices=DUPLICATE_MODES, default="skip")
    create_companies = serializers.BooleanField(default=True)
    assign_to = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(is_active=True), required=False, allow_null=True)

    def validate_assign_to(self, user):
        return check_assignment(self.context["request"].user, user)

    def validate_mapping(self, mapping):
        job = self.context["job"]
        keys = {c.key for c in columns_for(job.kind, importable=True)}
        cleaned, used = {}, set()
        for index, key in mapping.items():
            if not key:
                continue
            if not index.isdigit() or int(index) >= len(job.headers):
                raise serializers.ValidationError(_("Unknown column."))
            if key not in keys:
                raise serializers.ValidationError(_("Unknown field “%(key)s”.") % {"key": key})
            if key in used:
                raise serializers.ValidationError(_("Each field can only be used for one column."))
            used.add(key)
            cleaned[index] = key
        required = {"first_name", "full_name"} if job.kind == ContactImport.Kind.CONTACTS else {"name"}
        if not used & required:
            raise serializers.ValidationError(
                _("Choose the column with the first name (or full name).") if job.kind == ContactImport.Kind.CONTACTS
                else _("Choose the column with the company name.")
            )
        return cleaned


def field_list(kind: str) -> list[dict]:
    return [{"key": c.key, "label": str(c.label), "required": c.required} for c in columns_for(kind, importable=True)]


def job_data(job: ContactImport) -> dict:
    return {
        "id": job.pk,
        "kind": job.kind,
        "status": job.status,
        "file_name": job.file_name,
        "headers": job.headers,
        "sample": job.rows[:5],
        "fields": field_list(job.kind),
        "mapping": job.mapping,
        "options": job.options,
        "background": job.background,
        "total_rows": job.total_rows,
        "processed_rows": job.processed_rows,
        "created": job.created_count,
        "updated": job.updated_count,
        "skipped": job.skipped_count,
        "failed": job.failed_count,
        # Reasons are stored as message codes and rendered in the reader's language.
        "issues": [
            {"line": i["line"], "outcome": i["outcome"], "reason": issue_reason(i), "values": i["values"]}
            for i in job.issues[:ISSUES_IN_RESPONSE]
        ],
        "issue_count": len(job.issues),
        "error": job.error,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
    }


class ContactImportViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """CSV import of contacts or companies.

    1. POST /contact-imports/ (multipart `file`, `kind`) checks the file and suggests a column mapping.
    2. POST /contact-imports/{id}/preview/ shows how the first rows would be imported.
    3. POST /contact-imports/{id}/run/ imports: small files at once, larger ones in the background
       (poll GET /contact-imports/{id}/ for progress).
    4. GET /contact-imports/{id}/failed-rows/ downloads the rows that failed, with the reason.
    """

    module = "contacts"
    permission_classes = [ModulePermission]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    action_permissions = {a: "import" for a in ("list", "retrieve", "create", "preview", "run", "failed_rows", "template")}
    pagination_class = None

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ContactImport.objects.none()
        return ContactImport.objects.filter(created_by=self.request.user)

    def get_serializer_class(self):
        return UploadSerializer

    @extend_schema(operation_id="contact_imports_list", responses={200: dict})
    def list(self, request):
        """Your 10 most recent imports."""
        jobs = self.get_queryset().defer("rows")[:10]
        return Response([job_data_light(j) for j in jobs])

    @extend_schema(responses={200: dict})
    def retrieve(self, request, pk=None):
        return Response(job_data(self.get_object()))

    @extend_schema(request=UploadSerializer, responses={201: dict})
    def create(self, request):
        upload = UploadSerializer(data=request.data)
        upload.is_valid(raise_exception=True)
        kind = upload.validated_data["kind"]
        try:
            headers, rows = read_csv(upload.validated_data["file"])
        except CsvError as exc:
            raise ValidationError({"file": [str(exc)]})
        job = ContactImport.objects.create(
            kind=kind, file_name=upload.validated_data["file"].name[:255], headers=headers, rows=rows,
            total_rows=len(rows), mapping=suggest_mapping(kind, headers), created_by=request.user,
        )
        return Response(job_data(job), status=status.HTTP_201_CREATED)

    def _settings(self, request, job):
        if job.status != ContactImport.Status.UPLOADED:
            raise ValidationError({"detail": _("This import has already been run.")})
        settings = ImportSettingsSerializer(data=request.data, context={"request": request, "job": job})
        settings.is_valid(raise_exception=True)
        data = settings.validated_data
        job.mapping = data["mapping"]
        assignee = data.get("assign_to")
        job.options = {
            "duplicates": data["duplicates"],
            "create_companies": data["create_companies"],
            "assign_to": assignee.pk if assignee else None,
        }
        job.save(update_fields=["mapping", "options"])
        return job

    @extend_schema(request=ImportSettingsSerializer, responses={200: dict})
    @action(detail=True, methods=["post"])
    def preview(self, request, pk=None):
        job = self._settings(request, self.get_object())
        return Response({"rows": Importer(job, request.user).preview(), "total_rows": job.total_rows})

    @extend_schema(request=ImportSettingsSerializer, responses={200: dict, 202: dict})
    @action(detail=True, methods=["post"])
    def run(self, request, pk=None):
        from .tasks import run_contact_import

        job = self._settings(request, self.get_object())
        if job.total_rows > SYNC_LIMIT:
            job.status = ContactImport.Status.QUEUED
            job.background = True
            job.save(update_fields=["status", "background"])
            run_contact_import.delay(job.pk)
            job.refresh_from_db()
            return Response(job_data(job), status=status.HTTP_202_ACCEPTED)
        try:
            run_import(job.pk)
        except Exception:
            pass  # recorded on the job as "failed"
        job.refresh_from_db()
        return Response(job_data(job))

    @extend_schema(responses={(200, "text/csv"): str})
    @action(detail=True, methods=["get"], url_path="failed-rows")
    def failed_rows(self, request, pk=None):
        job = self.get_object()
        writer = CsvWriter(header=[_("Line"), *job.headers, _("Problem")])
        for issue in job.issues:
            if issue["outcome"] == "failed":
                writer.raw_row([issue["line"], *issue["values"], issue_reason(issue)])
        stem = job.file_name.rsplit(".", 1)[0]
        return csv_response(writer.getvalue(), f"{stem}-failed-rows.csv")

    @extend_schema(parameters=[OpenApiParameter("kind", str, enum=["contacts", "companies"])], responses={(200, "text/csv"): str})
    @action(detail=False, methods=["get"])
    def template(self, request):
        kind = request.query_params.get("kind", "contacts")
        if kind not in ContactImport.Kind.values:
            raise ValidationError({"kind": _("Unknown import type.")})
        writer = CsvWriter(columns_for(kind, importable=True, exportable=True))
        return csv_response(writer.getvalue(), f"{kind}-import-template.csv")


def job_data_light(job: ContactImport) -> dict:
    return {
        "id": job.pk, "kind": job.kind, "status": job.status, "file_name": job.file_name,
        "total_rows": job.total_rows, "processed_rows": job.processed_rows, "created": job.created_count,
        "updated": job.updated_count, "skipped": job.skipped_count, "failed": job.failed_count,
        "created_at": job.created_at, "finished_at": job.finished_at,
    }
