"""Attendance API: my day and month, check in/out, the team's day and month, corrections."""
import calendar
from datetime import date, timedelta

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _
from django.utils.translation import gettext_noop as N_
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.core.audit import log_action
from apps.core.models import AuditLog
from apps.core.office_time import office_now, office_today
from apps.core.permissions import has_perm, module_permission
from apps.leave import rules as leave_rules

from . import services, status as att
from .models import Attendance


def team_users(user, department=None):
    """People this person sees in the team views: their department (managers, with themselves), everyone (admins)."""
    if leave_rules.is_admin(user):
        qs = User.objects.filter(is_active=True)
        if department:
            qs = qs.filter(department_id=department)
    elif leave_rules.is_manager(user):
        qs = User.objects.filter(is_active=True, department_id=user.department_id)
    else:
        return User.objects.none()
    return qs.select_related("department").order_by("full_name", "id")


def can_see(viewer, person) -> bool:
    return viewer.pk == person.pk or team_users(viewer).filter(pk=person.pk).exists()


def _iso(value):
    """Datetimes as ISO text; other values (mode, note) as they are."""
    return value.isoformat() if hasattr(value, "isoformat") else (value or None)


def day_data(info: dict) -> dict:
    return {
        "status": info["status"],
        "late": info["late"],
        "check_in": _iso(info["check_in"]),
        "check_out": _iso(info["check_out"]),
        "mode": info["mode"],
        "note": info["note"],
        "corrected": info["corrected"],
        "leave": info["leave"],
        "holiday": info["holiday"],
    }


def _month(request) -> tuple[date, date]:
    raw = request.query_params.get("month") or office_today().strftime("%Y-%m")
    try:
        year, month = (int(x) for x in raw.split("-"))
        first = date(year, month, 1)
    except (ValueError, TypeError):
        raise ValidationError({"month": [_("Use YYYY-MM.")]})
    return first, date(year, month, calendar.monthrange(year, month)[1])


class TodayView(APIView):
    """My attendance today (for the dashboard card and the page), and my team's counts for managers and admins."""

    permission_classes = [module_permission("attendance", "view")]

    @extend_schema(responses={200: dict})
    def get(self, request):
        today = office_today()
        me = att.compute([request.user.pk], today, today)[(request.user.pk, today)]
        data = {"date": today.isoformat(), "me": day_data(me),
                "can_check_in": me["check_in"] is None, "can_check_out": me["check_in"] is not None and me["check_out"] is None}
        if has_perm(request.user, "visits", "view"):
            from apps.visits.models import Visit

            # A day with field visits: the check-in card suggests "on a field visit".
            from apps.visits.views import day_start

            mine = Visit.objects.filter(Q(assigned_to=request.user) | Q(companions=request.user), status=Visit.Status.PLANNED)
            today_visits = mine.filter(start__gte=day_start(today), start__lt=day_start(today + timedelta(days=1)))
            data["visits_today"] = today_visits.values("pk").distinct().count()
        team = list(team_users(request.user).values_list("pk", flat=True))
        if team:
            infos = att.compute(team, today, today)
            data["team"] = att.counts(infos.values())
        return Response(data)


class CheckInSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=Attendance.Mode.choices, default=Attendance.Mode.OFFICE)
    note = serializers.CharField(required=False, allow_blank=True, max_length=300, default="")


class CheckInView(APIView):
    permission_classes = [module_permission("attendance", "create")]

    @extend_schema(request=CheckInSerializer, responses={201: dict})
    def post(self, request):
        data = CheckInSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            record = services.check_in(request.user, data.validated_data["mode"], data.validated_data["note"])
        except services.AttendanceError as exc:
            raise ValidationError(exc.errors)
        return Response({"check_in": record.check_in.isoformat(), "mode": record.mode}, status=status.HTTP_201_CREATED)


class CheckOutView(APIView):
    permission_classes = [module_permission("attendance", "create")]

    @extend_schema(request=None, responses={200: dict})
    def post(self, request):
        try:
            record = services.check_out(request.user)
        except services.AttendanceError as exc:
            raise ValidationError(exc.errors)
        return Response({"check_in": record.check_in.isoformat(), "check_out": record.check_out.isoformat()})


class MonthView(APIView):
    """One person's month (mine, or a team member's for managers and admins), with totals."""

    permission_classes = [module_permission("attendance", "view")]

    @extend_schema(parameters=[OpenApiParameter("month", str, description="YYYY-MM"), OpenApiParameter("user", int)], responses={200: dict})
    def get(self, request):
        first, last = _month(request)
        person = request.user
        if uid := request.query_params.get("user"):
            person = get_object_or_404(User, pk=uid)
            if not can_see(request.user, person):
                raise PermissionDenied(_("You can't see this person's attendance."))
        infos = att.compute([person.pk], first, last)
        days = [{"date": d.isoformat(), **day_data(infos[(person.pk, d)])} for (_uid, d) in sorted(infos)]
        return Response({"user": person.pk, "user_name": person.full_name, "month": first.strftime("%Y-%m"),
                         "days": days, "totals": att.counts(infos.values())})


class TeamDayView(APIView):
    """Everyone in my team on one day: status, times, leave; plus the counts."""

    permission_classes = [module_permission("attendance", "edit")]

    @extend_schema(parameters=[OpenApiParameter("date", str), OpenApiParameter("department", int)], responses={200: dict})
    def get(self, request):
        day = parse_date(request.query_params.get("date") or "") or office_today()
        people = list(team_users(request.user, request.query_params.get("department")))
        infos = att.compute([p.pk for p in people], day, day)
        rows = [{"user": p.pk, "user_name": p.full_name, "department": p.department.name if p.department else None,
                 **day_data(infos[(p.pk, day)])} for p in people]
        return Response({"date": day.isoformat(), "rows": rows, "counts": att.counts(infos.values())})


class TeamMonthView(APIView):
    """My team × the days of a month: one status per cell (for the month grid)."""

    permission_classes = [module_permission("attendance", "edit")]

    @extend_schema(parameters=[OpenApiParameter("month", str), OpenApiParameter("department", int)], responses={200: dict})
    def get(self, request):
        first, last = _month(request)
        people = list(team_users(request.user, request.query_params.get("department")))
        infos = att.compute([p.pk for p in people], first, last)
        days = sorted({d for (_uid, d) in infos})
        return Response({
            "month": first.strftime("%Y-%m"),
            "days": [d.isoformat() for d in days],
            "rows": [{
                "user": p.pk, "user_name": p.full_name,
                "cells": [{"status": infos[(p.pk, d)]["status"], "late": infos[(p.pk, d)]["late"]} for d in days],
                "totals": att.counts(infos[(p.pk, d)] for d in days),
            } for p in people],
        })


class CorrectionSerializer(serializers.Serializer):
    user = serializers.IntegerField()
    date = serializers.DateField()
    check_in = serializers.TimeField(required=False, allow_null=True)
    check_out = serializers.TimeField(required=False, allow_null=True)
    mode = serializers.ChoiceField(choices=Attendance.Mode.choices, default=Attendance.Mode.OFFICE)
    note = serializers.CharField(required=False, allow_blank=True, max_length=300, default="")
    clear = serializers.BooleanField(required=False, default=False)


class CorrectView(APIView):
    """A manager or admin corrects one day of someone in their team (audited; the person is told)."""

    permission_classes = [module_permission("attendance", "edit")]

    @extend_schema(request=CorrectionSerializer, responses={200: dict})
    def post(self, request):
        data = CorrectionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        person = get_object_or_404(User, pk=v["user"])
        if not has_perm(request.user, "attendance", "edit") or not team_users(request.user).filter(pk=person.pk).exists():
            raise PermissionDenied(_("You can't correct this person's attendance."))
        try:
            record, before = services.correct(request.user, person, v["date"], check_in=v.get("check_in"), check_out=v.get("check_out"),
                                              mode=v["mode"], note=v["note"], clear=v["clear"])
        except services.AttendanceError as exc:
            raise ValidationError(exc.errors)
        after = None if record is None else {"check_in": record.check_in, "check_out": record.check_out, "mode": record.mode, "note": record.note}
        changes = {k: [_iso(before.get(k)) if before else None, _iso(after.get(k)) if after else None]
                   for k in ("check_in", "check_out", "mode", "note")
                   if (before or {}).get(k) != (after or {}).get(k)}
        target = record or person
        log_action(request.user, AuditLog.Action.UPDATE if before else AuditLog.Action.CREATE, target,
                   changes={"date": v["date"].isoformat(), **changes}, request=request,
                   object_repr=f"{person.full_name} {v['date']:%d/%m/%Y}", description=N_("Attendance corrected"))
        infos = att.compute([person.pk], v["date"], v["date"], now=office_now())
        return Response({"user": person.pk, "date": v["date"].isoformat(), **day_data(infos[(person.pk, v["date"])])})
