"""Checking in and out, corrections by managers, and the "forgot to check in / out" reminders."""
from datetime import datetime, time, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounts.models import User
from apps.core.models import OrganizationSettings
from apps.core.office_time import office_now, office_tz
from apps.leave.models import LeaveRequest
from apps.leave.services import holidays_between
from apps.notifications.models import NotificationType
from apps.notifications.services import notify

from .models import Attendance, AttendanceReminder

CHECK_IN_REMINDER_AFTER = timedelta(minutes=15)  # after the late threshold
CHECK_OUT_REMINDER_AFTER = timedelta(minutes=30)  # after the office closes


class AttendanceError(ValueError):
    def __init__(self, errors: dict):
        self.errors = errors
        super().__init__(next(iter(errors.values())))


def check_in(user, mode=Attendance.Mode.OFFICE, note="", *, now=None) -> Attendance:
    now = now or timezone.now()
    today = now.astimezone(office_tz()).date()
    with transaction.atomic():
        record, _created = Attendance.objects.select_for_update().get_or_create(user=user, date=today)
        if record.check_in:
            raise AttendanceError({"detail": _("You have already checked in today.")})
        record.check_in, record.mode, record.note = now, mode, note.strip()[:300]
        record.save(update_fields=["check_in", "mode", "note", "updated_at"])
    return record


def check_out(user, *, now=None) -> Attendance:
    now = now or timezone.now()
    today = now.astimezone(office_tz()).date()
    with transaction.atomic():
        record = Attendance.objects.select_for_update().filter(user=user, date=today).first()
        if record is None or not record.check_in:
            raise AttendanceError({"detail": _("Check in first.")})
        if record.check_out:
            raise AttendanceError({"detail": _("You have already checked out today.")})
        record.check_out = now
        record.save(update_fields=["check_out", "updated_at"])
    return record


def correct(actor, user, day, *, check_in=None, check_out=None, mode=Attendance.Mode.OFFICE, note="", clear=False):
    """A manager's or admin's correction of one day (times are office wall-clock times).
    `clear` removes the record (the day shows as absent, leave or off again). Returns (record or None, before)."""
    tz = office_tz()
    with transaction.atomic():
        record = Attendance.objects.select_for_update().filter(user=user, date=day).first()
        before = None
        if record is not None:
            before = {"check_in": record.check_in, "check_out": record.check_out, "mode": record.mode, "note": record.note}
        if clear:
            if record is not None:
                record.delete()
            result = None
        else:
            if check_in is None:
                raise AttendanceError({"check_in": _("Give the check-in time.")})
            start = datetime.combine(day, check_in, tzinfo=tz)
            end = datetime.combine(day, check_out, tzinfo=tz) if check_out else None
            if end is not None and end <= start:
                raise AttendanceError({"check_out": _("Check-out must be after check-in.")})
            if day > office_now().date():
                raise AttendanceError({"date": _("Days that haven't happened yet can't be filled in.")})
            record = record or Attendance(user=user, date=day)
            record.check_in, record.check_out, record.mode, record.note = start, end, mode, note.strip()[:300]
            record.corrected_by, record.corrected_at = actor, timezone.now()
            record.save()
            result = record
        if actor.pk != user.pk:
            params = {
                "actor": actor.full_name, "date": day.isoformat(), "cleared": clear,
                "check_in": result.check_in.isoformat() if result else "", "check_out": result.check_out.isoformat() if result and result.check_out else "",
            }
            transaction.on_commit(lambda: notify(user, NotificationType.ATTENDANCE, link=f"/attendance?month={day:%Y-%m}", actor=actor,
                                                 message="attendance_corrected", params=params))
    return result, before


# ================================================================ reminders


def _claim(user, day, kind) -> bool:
    try:
        with transaction.atomic():
            AttendanceReminder.objects.create(user=user, date=day, kind=kind)
        return True
    except IntegrityError:
        return False  # already reminded (also when two runs overlap)


def send_reminders(now=None) -> dict:
    """Every 5 minutes (Celery Beat): once a day, remind people who haven't checked in some time after the
    late threshold, and people who checked in but not out half an hour after closing. Only on working
    days that aren't office holidays; nobody on full-day leave."""
    org = OrganizationSettings.cached()
    sent = {"in": 0, "out": 0}
    if not org.attendance_reminders:
        return sent
    now = (now or timezone.now()).astimezone(office_tz())
    today = now.date()
    if today.weekday() not in org.working_days or holidays_between(today, today):
        return sent
    opens = datetime.combine(today, org.office_opens, tzinfo=office_tz())
    closes = datetime.combine(today, org.office_closes, tzinfo=office_tz())
    records = {a.user_id: a for a in Attendance.objects.filter(date=today)}
    if opens + timedelta(minutes=org.late_after_minutes) + CHECK_IN_REMINDER_AFTER <= now < closes:
        on_leave = set(
            LeaveRequest.objects.filter(status=LeaveRequest.Status.APPROVED, start_date__lte=today, end_date__gte=today, half_day="")
            .values_list("user_id", flat=True)
        )
        already = set(AttendanceReminder.objects.filter(date=today, kind=AttendanceReminder.Kind.CHECK_IN).values_list("user_id", flat=True))
        for user in User.objects.filter(is_active=True).exclude(pk__in=on_leave | already):
            rec = records.get(user.pk)
            if rec and rec.check_in:
                continue
            if _claim(user, today, AttendanceReminder.Kind.CHECK_IN):
                notify(user, NotificationType.ATTENDANCE, link="/attendance", message="attendance_check_in",
                       params={"opens": datetime.combine(today, org.office_opens).isoformat()})
                sent["in"] += 1
    if now >= closes + CHECK_OUT_REMINDER_AFTER:
        for rec in Attendance.objects.filter(date=today, check_in__isnull=False, check_out__isnull=True, user__is_active=True).select_related("user"):
            if _claim(rec.user, today, AttendanceReminder.Kind.CHECK_OUT):
                notify(rec.user, NotificationType.ATTENDANCE, link="/attendance", message="attendance_check_out",
                       params={"check_in": rec.check_in.isoformat()})
                sent["out"] += 1
    return sent


def time_of(value: str | None) -> time | None:
    if not value:
        return None
    h, m = value.split(":")[:2]
    return time(int(h), int(m))
