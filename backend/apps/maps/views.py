"""The map: visits with their pins and check-in locations, contacts', companies' and vendors' pins, and address search.

- The map page is for managers and admins (visits "view_map"): their department's visits (admins: everyone's) in a
  date range of up to 31 days, by person and status. A visit is shown at its own pin, or else at its contact's,
  company's or vendor's.
- Check-in and check-out locations are sent only to those allowed to see them (the person, their department's
  managers, admins), as for the visit itself; after 90 days they're gone (removed by the daily job).
- Contacts and companies: those the viewer can see; vendors: the shared directory (active ones).
- Address search (anyone who can plan visits) goes through Nominatim from the server, cached and one a second
  (see geocode.py); it only centres the map.
"""
from datetime import timedelta

from django.db.models import Q
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _
from django.utils.translation import get_language
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.contacts.visibility import visible_companies, visible_contacts
from apps.core.office_time import office_today
from apps.core.permissions import has_perm, module_permission
from apps.errands import rules as errand_rules
from apps.errands.models import Errand
from apps.vendors.models import Vendor
from apps.visits import rules
from apps.visits.models import Visit
from apps.visits.serializers import check_data
from apps.visits.views import day_start

from . import geocode

MAX_DAYS = 31
MAX_RECORDS = 500
SHOWN = (Visit.Status.PENDING, Visit.Status.PLANNED, Visit.Status.DONE)


def _num(value):
    return str(value) if value is not None else None


def _pin(obj) -> dict:
    return {"latitude": _num(obj.latitude), "longitude": _num(obj.longitude)}


def errand_data(e) -> dict:
    record = e.contact or e.company or e.vendor
    if e.latitude is not None:
        pin, source = _pin(e), "errand"
    elif record is not None and record.latitude is not None:
        pin, source = _pin(record), "record"
    else:
        pin, source = {"latitude": None, "longitude": None}, None
    return {
        "id": e.pk, "title": e.title, "kind": e.kind, "status": e.status, "due_at": e.due_at, "place": e.place,
        "assigned_to_name": e.assigned_to.full_name if e.assigned_to else None, **pin, "pin_source": source,
    }


def visit_data(v, viewer) -> dict:
    record = v.contact or v.company or v.vendor
    if v.latitude is not None:
        pin, source = _pin(v), "visit"
    elif record is not None and record.latitude is not None:
        pin, source = _pin(record), "record"
    else:
        pin, source = {"latitude": None, "longitude": None}, None
    return {
        "id": v.pk, "title": v.title, "status": v.status, "purpose": v.purpose, "start": v.start, "end": v.end,
        "assigned_to": v.assigned_to_id, "assigned_to_name": v.assigned_to.full_name, "place": v.place,
        **pin, "pin_source": source,
        "checks": [check_data(c, viewer, v) for c in v.checks.all()],
    }


class MapConfigView(APIView):
    """What the map needs to know first: whether address search is set up."""

    permission_classes = [module_permission("visits", "view")]

    @extend_schema(responses={200: dict})
    def get(self, request):
        return Response({"search_enabled": geocode.enabled(), "can_view_map": has_perm(request.user, "visits", "view_map")})


class MapView(APIView):
    permission_classes = [module_permission("visits", "view_map")]

    @extend_schema(
        parameters=[
            OpenApiParameter("from", str, description="First day (YYYY-MM-DD, default today)"),
            OpenApiParameter("to", str, description="Last day (default the first; at most 31 days)"),
            OpenApiParameter("person", int),
            OpenApiParameter("status", str, enum=["planned", "done", "pending", "all"], description="Default all (not cancelled or rejected)"),
        ],
        responses={200: dict},
    )
    def get(self, request):
        user, p = request.user, request.query_params
        first = parse_date(p.get("from") or "") or office_today()
        last = parse_date(p.get("to") or "") or first
        if last < first or (last - first).days >= MAX_DAYS:
            raise ValidationError({"from": [_("Give a date range (from, to) of at most %(n)s days.") % {"n": MAX_DAYS}]})
        visits = rules.visible_visits(user).filter(start__gte=day_start(first), start__lt=day_start(last + timedelta(days=1)))
        if not rules.is_admin(user):
            visits = visits.filter(assigned_to__department_id=user.department_id)
        status = p.get("status") or "all"
        visits = visits.filter(status=status) if status in SHOWN else visits.filter(status__in=SHOWN)
        if (person := p.get("person")) and person.isdigit():
            visits = visits.filter(assigned_to_id=int(person))
        visits = visits.select_related("contact", "company", "vendor", "assigned_to").prefetch_related("checks__user").order_by("start")
        records = lambda qs: [  # noqa: E731
            {"id": r.pk, "name": getattr(r, "full_name", None) or r.name, "city": r.city, **_pin(r)}
            for r in qs.filter(latitude__isnull=False).order_by("pk")[:MAX_RECORDS]
        ]
        contacts = visible_contacts(user) if has_perm(user, "contacts", "view") else visible_contacts(user).none()
        companies = visible_companies(user) if has_perm(user, "contacts", "view") else visible_companies(user).none()
        vendors = Vendor.objects.filter(is_active=True) if has_perm(user, "vendors", "view") else Vendor.objects.none()
        errands = Errand.objects.none()
        if has_perm(user, "errands", "view"):
            errands = errand_rules.visible_errands(user).filter(
                Q(due_at__gte=day_start(first), due_at__lt=day_start(last + timedelta(days=1)))
                | Q(due_at__isnull=True, status__in=Errand.ACTIVE)
            ).exclude(status=Errand.Status.CANCELLED)
            if not rules.is_admin(user):
                errands = errands.filter(department_id=user.department_id)
            if (person := p.get("person")) and person.isdigit():
                errands = errands.filter(assigned_to_id=int(person))
            errands = errands.select_related("contact", "company", "vendor", "assigned_to").order_by("due_at", "id")
        return Response({
            "from": first, "to": last, "search_enabled": geocode.enabled(),
            "visits": [visit_data(v, user) for v in visits[:MAX_RECORDS]],
            "errands": [errand_data(e) for e in errands[:MAX_RECORDS]],
            "contacts": records(contacts), "companies": records(companies), "vendors": records(vendors),
        })


class SearchView(APIView):
    """Find an address to centre the map on (Nominatim through our server). Press Search; no type-ahead."""

    permission_classes = [module_permission("visits", "view")]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "map_search"

    @extend_schema(parameters=[OpenApiParameter("q", str, required=True)], responses={200: dict})
    def get(self, request):
        query = geocode.normalise(request.query_params.get("q", ""))
        if len(query) < geocode.MIN_LENGTH:
            raise ValidationError({"q": [_("Type at least %(n)s characters.") % {"n": geocode.MIN_LENGTH}]})
        try:
            results, cached = geocode.search(query, (get_language() or "en")[:2])
        except geocode.SearchError as exc:
            messages = {
                "disabled": _("Address search isn't set up yet: an admin needs to add a contact email (NOMINATIM_CONTACT_EMAIL) to the server settings. You can still drop the pin on the map or use your location."),
                "busy": _("Address search is busy. Try again in a moment."),
                "failed": _("Address search didn't answer. Try again, or drop the pin on the map."),
            }
            return Response({"detail": messages[exc.code], "code": f"search_{exc.code}"}, status=503 if exc.code != "busy" else 429)
        return Response({"results": results, "cached": cached})
