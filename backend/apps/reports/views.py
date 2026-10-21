"""Reports API: managers see their department, admins everyone (or one department). Exports (PDF, Excel) need the
reports export permission and are written to the audit log, like the CSV exports."""
import re
from urllib.parse import quote

from django.http import HttpResponse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_noop as N_
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.contacts.transfer import _log_export
from apps.core.permissions import module_permission

from . import documents, render, task_reports
from .scope import period_for, scope_for

FORMATS = {
    "pdf": ("application/pdf", render.render_pdf),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", render.render_xlsx),
}
SCOPE_PARAMS = [
    OpenApiParameter("department", int, description="Admins: one department (managers always see their own)"),
    OpenApiParameter("person", int, description="One person in the report's scope"),
]
PERIOD_PARAMS = [OpenApiParameter("from", str, description="First office day (YYYY-MM-DD)"), OpenApiParameter("to", str, description="Last office day")]
FORMAT_PARAM = [OpenApiParameter("file", str, enum=list(FORMATS), required=True)]


def _people(scope) -> list[dict]:
    return [{"id": p.pk, "name": p.full_name, "department": p.department_id} for p in scope.people]


def local_name(title: str, stem: str) -> str:
    """The file's name in the reader's language: the report's title and its dates ("Field visits 2026-10-01 – 2026-10-31").
    Sent as filename* (RFC 6266), with the plain ASCII stem as the fallback filename."""
    dates = re.search(r"(\d{4}-\d{2}-\d{2})(?:-(\d{4}-\d{2}-\d{2}))?$", stem)
    if not dates:
        return title
    return f"{title} {dates[1]}" + (f" – {dates[2]}" if dates[2] else "")


def _export(request, doc, stem, kind, rows, description):
    fmt = request.query_params.get("file")  # (DRF keeps ?format= for choosing a renderer)
    if fmt not in FORMATS:
        raise ValidationError({"file": [_("Choose PDF or Excel.")]})
    content_type, make = FORMATS[fmt]
    body = make(doc)
    _log_export(request, kind, rows, description)  # the format and filters are in the logged query parameters
    response = HttpResponse(body, content_type=content_type)
    local = quote(f"{local_name(doc.title, stem)}.{fmt}")
    response["Content-Disposition"] = f"attachment; filename=\"{stem}.{fmt}\"; filename*=UTF-8''{local}"
    response["X-Content-Type-Options"] = "nosniff"
    return response


class TaskCompletionView(APIView):
    """Tasks due in the period: done, on time, late, overdue and still open, by person, department and overall."""

    permission_classes = [module_permission("reports", "view")]

    @extend_schema(parameters=[*PERIOD_PARAMS, *SCOPE_PARAMS], responses={200: dict})
    def get(self, request):
        first, last = period_for(request.query_params)
        scope = scope_for(request.user, request.query_params)
        data = task_reports.completion(request.user, scope, first, last)
        return Response({**data, "scope": {"department": scope.department.pk if scope.department else None,
                                           "person": scope.person.pk if scope.person else None}})


class TaskCompletionExportView(APIView):
    permission_classes = [module_permission("reports", "export")]

    @extend_schema(parameters=[*PERIOD_PARAMS, *SCOPE_PARAMS, *FORMAT_PARAM], responses={(200, "application/octet-stream"): bytes})
    def get(self, request):
        first, last = period_for(request.query_params)
        scope = scope_for(request.user, request.query_params)
        data = task_reports.completion(request.user, scope, first, last)
        doc = documents.completion_document(data, scope, request.user)
        return _export(request, doc, f"task-completion-{first:%Y-%m-%d}-{last:%Y-%m-%d}", "task completion report", len(data["people"]),
                       N_("Exported the task completion report"))


class OverdueTasksView(APIView):
    """Open tasks past their due date, as of today: by person (how late) and the most overdue tasks."""

    permission_classes = [module_permission("reports", "view")]

    @extend_schema(parameters=SCOPE_PARAMS, responses={200: dict})
    def get(self, request):
        scope = scope_for(request.user, request.query_params)
        data = task_reports.overdue(request.user, scope)
        return Response(data)


class OverdueTasksExportView(APIView):
    permission_classes = [module_permission("reports", "export")]

    @extend_schema(parameters=[*SCOPE_PARAMS, *FORMAT_PARAM], responses={(200, "application/octet-stream"): bytes})
    def get(self, request):
        scope = scope_for(request.user, request.query_params)
        data = task_reports.overdue(request.user, scope)
        doc = documents.overdue_document(data, scope, request.user)
        return _export(request, doc, f"overdue-tasks-{timezone.localdate():%Y-%m-%d}", "overdue tasks report", data["total"],
                       N_("Exported the overdue tasks report"))


class PeopleView(APIView):
    """Whom the viewer's reports cover (for the person filter), by department for admins."""

    permission_classes = [module_permission("reports", "view")]

    @extend_schema(parameters=SCOPE_PARAMS[:1], responses={200: dict})
    def get(self, request):
        scope = scope_for(request.user, {"department": request.query_params.get("department")})
        return Response({"people": _people(scope), "department": scope.department.pk if scope.department else None})


BY_PARAM = [OpenApiParameter("by", str, enum=["week", "month"], description="Group by office week (from its week start) or month")]


def _by(request) -> str:
    by = request.query_params.get("by") or "week"
    if by not in ("week", "month"):
        raise ValidationError({"by": [_("Group by week or month.")]})
    return by


class InteractionsView(APIView):
    """Calls, meetings, emails, WhatsApp messages and visit reports with clients, per week or month and per person."""

    permission_classes = [module_permission("reports", "view")]

    @extend_schema(parameters=[*PERIOD_PARAMS, *BY_PARAM, *SCOPE_PARAMS], responses={200: dict})
    def get(self, request):
        from . import client_reports

        first, last = period_for(request.query_params)
        scope = scope_for(request.user, request.query_params)
        return Response(client_reports.interactions(request.user, scope, first, last, _by(request)))


class InteractionsExportView(APIView):
    permission_classes = [module_permission("reports", "export")]

    @extend_schema(parameters=[*PERIOD_PARAMS, *BY_PARAM, *SCOPE_PARAMS, *FORMAT_PARAM], responses={(200, "application/octet-stream"): bytes})
    def get(self, request):
        from . import client_reports

        first, last = period_for(request.query_params)
        scope = scope_for(request.user, request.query_params)
        data = client_reports.interactions(request.user, scope, first, last, _by(request))
        doc = documents.interactions_document(data, scope, request.user)
        return _export(request, doc, f"client-interactions-{first:%Y-%m-%d}-{last:%Y-%m-%d}", "client interactions report",
                       data["totals"]["total"], N_("Exported the client interactions report"))


class PipelineView(APIView):
    """Leads added in the period and how far they got; status changes and wins in the period."""

    permission_classes = [module_permission("reports", "view")]

    @extend_schema(parameters=[*PERIOD_PARAMS, *SCOPE_PARAMS], responses={200: dict})
    def get(self, request):
        from . import client_reports

        first, last = period_for(request.query_params)
        scope = scope_for(request.user, request.query_params)
        return Response(client_reports.pipeline(request.user, scope, first, last))


class PipelineExportView(APIView):
    permission_classes = [module_permission("reports", "export")]

    @extend_schema(parameters=[*PERIOD_PARAMS, *SCOPE_PARAMS, *FORMAT_PARAM], responses={(200, "application/octet-stream"): bytes})
    def get(self, request):
        from . import client_reports

        first, last = period_for(request.query_params)
        scope = scope_for(request.user, request.query_params)
        data = client_reports.pipeline(request.user, scope, first, last)
        doc = documents.pipeline_document(data, scope, request.user)
        return _export(request, doc, f"lead-pipeline-{first:%Y-%m-%d}-{last:%Y-%m-%d}", "lead pipeline report", data["funnel"]["created"],
                       N_("Exported the lead pipeline report"))


def _period_report(name, make, document, stem, kind, rows, description):
    """A view and an export view for a report over a period."""

    class ReportView(APIView):
        permission_classes = [module_permission("reports", "view")]

        @extend_schema(parameters=[*PERIOD_PARAMS, *SCOPE_PARAMS], responses={200: dict})
        def get(self, request):
            first, last = period_for(request.query_params)
            return Response(make(request.user, scope_for(request.user, request.query_params), first, last))

    class ExportView(APIView):
        permission_classes = [module_permission("reports", "export")]

        @extend_schema(parameters=[*PERIOD_PARAMS, *SCOPE_PARAMS, *FORMAT_PARAM], responses={(200, "application/octet-stream"): bytes})
        def get(self, request):
            first, last = period_for(request.query_params)
            scope = scope_for(request.user, request.query_params)
            data = make(request.user, scope, first, last)
            return _export(request, document(data, scope, request.user), f"{stem}-{first:%Y-%m-%d}-{last:%Y-%m-%d}", kind, rows(data), description)

    ReportView.__name__ = ReportView.__qualname__ = f"{name}View"
    ExportView.__name__ = ExportView.__qualname__ = f"{name}ExportView"
    return ReportView, ExportView


def _field():
    from . import field_reports

    return field_reports


FieldVisitsView, FieldVisitsExportView = _period_report(
    "FieldVisits", lambda *a: _field().visits(*a), documents.field_visits_document, "field-visits", "field visits report",
    lambda d: d["totals"]["scheduled"], N_("Exported the field visits report"))
ErrandsView, ErrandsExportView = _period_report(
    "Errands", lambda *a: _field().errands(*a), documents.errands_document, "errands", "errands report",
    lambda d: d["totals"]["asked"], N_("Exported the errands report"))


def _attendance():
    from . import attendance_reports

    return attendance_reports


AttendanceView, AttendanceExportView = _period_report(
    "Attendance", lambda *a: _attendance().summary(*a), documents.attendance_document, "attendance-leave", "attendance and leave report",
    lambda d: len(d["people"]), N_("Exported the attendance and leave report"))
