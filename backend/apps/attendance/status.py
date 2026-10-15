"""Each person's attendance status per day, from check-ins, approved leave, the working week and office
holidays. Three queries for any number of people and days (records, leave, holidays).

Statuses:
- present / field / remote: checked in (in the office, on a field visit, working from elsewhere); `late`
  when the check-in came more than the grace minutes after the office opened (office and remote only);
- leave: approved leave (a half day is marked; someone on half-day leave who checked in is present);
- off: not a working day, or an office holiday;
- not_in: today, a working day, no check-in yet;
- absent: a past working day with no check-in and no leave;
- upcoming: a future working day.
"""
from datetime import date, datetime, timedelta

from apps.core.models import OrganizationSettings
from apps.core.office_time import office_now, office_tz
from apps.leave.models import LeaveRequest
from apps.leave.services import holidays_between

from .models import Attendance

PRESENT, FIELD, REMOTE, LEAVE, OFF, NOT_IN, ABSENT, UPCOMING = "present", "field", "remote", "leave", "off", "not_in", "absent", "upcoming"
MODE_STATUS = {Attendance.Mode.OFFICE: PRESENT, Attendance.Mode.FIELD: FIELD, Attendance.Mode.REMOTE: REMOTE}


def late_after(day: date) -> datetime:
    org = OrganizationSettings.cached()
    return datetime.combine(day, org.office_opens, tzinfo=office_tz()) + timedelta(minutes=org.late_after_minutes)


def compute(user_ids, first: date, last: date, *, now=None) -> dict[tuple[int, date], dict]:
    """{(user id, day): {"status", "late", "check_in", "check_out", "mode", "note", "record", "leave", "holiday", "corrected"}}"""
    user_ids = list(user_ids)
    now = (now or office_now()).astimezone(office_tz())
    today = now.date()
    org = OrganizationSettings.cached()
    working = set(org.working_days)
    holidays = holidays_between(first, last)
    records = {
        (a.user_id, a.date): a
        for a in Attendance.objects.filter(user_id__in=user_ids, date__gte=first, date__lte=last).select_related("corrected_by")
    }
    leave: dict[tuple[int, date], LeaveRequest] = {}
    for r in LeaveRequest.objects.filter(
        user_id__in=user_ids, status=LeaveRequest.Status.APPROVED, start_date__lte=last, end_date__gte=first
    ).select_related("leave_type"):
        day = max(r.start_date, first)
        while day <= min(r.end_date, last):
            leave[(r.user_id, day)] = r
            day += timedelta(days=1)
    out = {}
    day = first
    while day <= last:
        threshold = late_after(day)
        for uid in user_ids:
            rec, lv = records.get((uid, day)), leave.get((uid, day))
            info = {
                "record": rec.pk if rec else None,
                "check_in": rec.check_in if rec else None,
                "check_out": rec.check_out if rec else None,
                "mode": rec.mode if rec else None,
                "note": rec.note if rec else "",
                "corrected": bool(rec and rec.corrected_by_id),
                "late": False,
                "leave": {"type": lv.leave_type.name, "type_ur": lv.leave_type.name_ur, "half_day": lv.half_day} if lv else None,
                "holiday": holidays.get(day),
            }
            if rec and rec.check_in:
                info["status"] = MODE_STATUS.get(rec.mode, PRESENT)
                info["late"] = rec.mode != Attendance.Mode.FIELD and rec.check_in > threshold
            elif lv:
                info["status"] = LEAVE
            elif day.weekday() not in working or day in holidays:
                info["status"] = OFF
            elif day > today:
                info["status"] = UPCOMING
            elif day == today:
                info["status"] = NOT_IN
            else:
                info["status"] = ABSENT
            out[(uid, day)] = info
        day += timedelta(days=1)
    return out


def counts(infos) -> dict[str, int]:
    """How many people are in each status (and how many of the present ones were late)."""
    out = {s: 0 for s in (PRESENT, FIELD, REMOTE, LEAVE, OFF, NOT_IN, ABSENT, UPCOMING)}
    out["late"] = 0
    for info in infos:
        out[info["status"]] += 1
        out["late"] += int(info["late"])
    return out
