"""Planning, changing, deciding, closing and cancelling field visits, and their reminders."""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.notifications.models import NotificationType
from apps.notifications.services import notify

from . import rules
from .models import Visit

REMINDER_LEAD = timedelta(minutes=30)  # time to set off
MAX_LENGTH = timedelta(hours=12)
LINK = "/visits"
TARGETS = ("contact", "company", "vendor")
WATCHED = ("start", "end", "address", "city", "place_name", "contact", "company", "vendor", "latitude", "longitude")


class VisitError(ValueError):
    """{field: message}"""

    def __init__(self, errors: dict):
        self.errors = errors
        super().__init__(next(iter(errors.values())))


def link(visit) -> str:
    return f"{LINK}?visit={visit.pk}"


def check(planner, data: dict, *, instance=None):
    """Raise VisitError unless the visit's details make sense and the planner may plan it."""
    start, end = data.get("start"), data.get("end")
    if end <= start:
        raise VisitError({"end": _("The visit has to end after it starts.")})
    if end - start > MAX_LENGTH:
        raise VisitError({"end": _("A visit can last 12 hours at most.")})
    if sum(1 for t in TARGETS if data.get(t)) > 1:
        raise VisitError({"contact": _("Choose one: a contact, a company or a vendor.")})
    if not any(data.get(t) for t in TARGETS) and not (data.get("place_name") or "").strip():
        raise VisitError({"place_name": _("Say who or where the visit is.")})
    if (data.get("latitude") is None) != (data.get("longitude") is None):
        raise VisitError({"latitude": _("Give both latitude and longitude, or neither.")})
    person = data["assigned_to"]
    if not person.is_active:
        raise VisitError({"assigned_to": _("This person's account is not active.")})
    if not rules.can_plan_for(planner, person):
        raise VisitError({"assigned_to": _("You can plan visits for yourself, or for your department if you manage it.")})
    for c in data.get("companions") or []:
        if c.pk == person.pk:
            raise VisitError({"companions": _("The person responsible is already going.")})
        if not c.is_active or not (rules.is_admin(planner) or c.department_id == person.department_id):
            raise VisitError({"companions": _("Companions come from the same department.")})


def plan(planner, data: dict) -> Visit:
    check(planner, data)
    companions = list(data.pop("companions", None) or [])
    pending = rules.needs_approval(planner, data["assigned_to"])
    with transaction.atomic():
        visit = Visit.objects.create(**data, created_by=planner, status=Visit.Status.PENDING if pending else Visit.Status.PLANNED)
        visit.companions.set(companions)
        pk, actor_pk = visit.pk, planner.pk
        if pending:
            transaction.on_commit(lambda: _announce_request(pk))
        else:
            transaction.on_commit(lambda: _announce(pk, "visit_assigned", actor_pk))
    return visit


def change(actor, visit, data: dict) -> dict:
    """Change an open visit; returns {field: [old, new]} for the audit log."""
    if not rules.can_change(actor, visit):
        raise PermissionError
    companions = data.pop("companions", None)
    merged = {f: getattr(visit, f) for f in (*WATCHED, "assigned_to", "title", "purpose", "notes", "task")}
    merged["companions"] = companions if companions is not None else list(visit.companions.all())
    merged.update(data)
    check(actor, merged, instance=visit)
    before = {f: getattr(visit, f) for f in merged if f != "companions"}
    old_people = {visit.assigned_to_id, *visit.companions.values_list("pk", flat=True)}
    changes = {}
    with transaction.atomic():
        for field, value in data.items():
            if before.get(field) != value:
                changes[field] = [str(before.get(field) or ""), str(value or "")]
                setattr(visit, field, value)
        visit.save()
        if companions is not None:
            old = sorted(u.full_name for u in visit.companions.all())
            visit.companions.set(companions)
            new = sorted(u.full_name for u in companions)
            if old != new:
                changes["companions"] = [", ".join(old), ", ".join(new)]
        moved = any(f in changes for f in WATCHED)
        new_people = {visit.assigned_to_id, *(c.pk for c in visit.companions.all())}
        pk, actor_pk = visit.pk, actor.pk
        added, removed = new_people - old_people, old_people - new_people
        if visit.status == Visit.Status.PLANNED:
            transaction.on_commit(lambda: _announce_change(pk, actor_pk, added, removed, moved))
    return changes


def decide(actor, visit, *, approve: bool, note="") -> Visit:
    if not rules.can_decide(actor, visit):
        raise PermissionError
    visit.status = Visit.Status.PLANNED if approve else Visit.Status.REJECTED
    visit.decided_by, visit.decided_at, visit.decision_note = actor, timezone.now(), note.strip()[:300]
    visit.save(update_fields=["status", "decided_by", "decided_at", "decision_note", "updated_at"])
    pk = visit.pk
    transaction.on_commit(lambda: _announce_decision(pk))
    return visit


def close(actor, visit, note="") -> Visit:
    """Mark a planned visit done (the report comes in a later slice)."""
    if not rules.can_close(actor, visit):
        raise PermissionError
    if visit.start > timezone.now() + timedelta(hours=1):
        raise VisitError({"detail": _("A visit can be marked done once it has started.")})
    visit.status = Visit.Status.DONE
    visit.closed_by, visit.closed_at, visit.close_note = actor, timezone.now(), note.strip()[:300]
    visit.save(update_fields=["status", "closed_by", "closed_at", "close_note", "updated_at"])
    pk, actor_pk = visit.pk, actor.pk
    transaction.on_commit(lambda: _announce_done(pk, actor_pk))
    return visit


def cancel(actor, visit, reason="") -> Visit:
    if not rules.can_change(actor, visit):
        raise PermissionError
    was_pending = visit.status == Visit.Status.PENDING
    visit.status = Visit.Status.CANCELLED
    visit.closed_by, visit.closed_at, visit.close_note = actor, timezone.now(), reason.strip()[:300]
    visit.save(update_fields=["status", "closed_by", "closed_at", "close_note", "updated_at"])
    pk, actor_pk = visit.pk, actor.pk
    transaction.on_commit(lambda: _announce_cancel(pk, actor_pk, was_pending))
    return visit


def send_reminders(now=None) -> int:
    """Planned visits starting within 30 minutes: the people going are reminded once per start time."""
    now = now or timezone.now()
    due = (
        Visit.objects.filter(status=Visit.Status.PLANNED, start__gt=now, start__lte=now + REMINDER_LEAD)
        .select_related("assigned_to", "contact", "company", "vendor").prefetch_related("companions")
    )
    sent = 0
    for visit in due:
        if visit.reminded_start == visit.start:
            continue
        if not Visit.objects.filter(pk=visit.pk).exclude(reminded_start=visit.start).update(reminded_start=visit.start):
            continue  # another run got there first
        notify(_people(visit), NotificationType.VISIT, link=link(visit), message="visit_reminder", params=_params(visit))
        sent += 1
    return sent


# ================================================================ notifications


def _people(visit):
    return [visit.assigned_to, *visit.companions.all()]


def _params(visit, actor=None) -> dict:
    return {
        "title": visit.title, "place": visit.place, "address": ", ".join(x for x in (visit.address, visit.city) if x),
        "start": visit.start.isoformat(), "end": visit.end.isoformat(), "name": visit.assigned_to.full_name,
        "actor": actor.full_name if actor else "", "note": visit.decision_note or visit.close_note,
    }


def _load(pk):
    return Visit.objects.select_related("assigned_to", "contact", "company", "vendor", "created_by").prefetch_related("companions").get(pk=pk)


def _user(pk):
    from apps.accounts.models import User

    return User.objects.get(pk=pk)


def _announce(pk, message, actor_pk):
    visit, actor = _load(pk), _user(actor_pk)
    notify(_people(visit), NotificationType.VISIT, link=link(visit), actor=actor, message=message, params=_params(visit, actor))


def _announce_request(pk):
    visit = _load(pk)
    notify(rules.approvers_for(visit.assigned_to), NotificationType.APPROVAL_REQUEST, link=f"{LINK}?tab=approvals",
           actor=visit.assigned_to, message="visit_request", params=_params(visit, visit.assigned_to))
    others = [c for c in visit.companions.all()]
    if others:
        notify(others, NotificationType.VISIT, link=link(visit), actor=visit.assigned_to, message="visit_assigned",
               params=_params(visit, visit.assigned_to))


def _announce_decision(pk):
    visit = _load(pk)
    message = "visit_approved" if visit.status == Visit.Status.PLANNED else "visit_rejected"
    notify(visit.assigned_to, NotificationType.APPROVAL_RESULT, link=link(visit), actor=visit.decided_by, message=message,
           params=_params(visit, visit.decided_by))


def _announce_change(pk, actor_pk, added, removed, moved):
    from apps.accounts.models import User

    visit, actor = _load(pk), _user(actor_pk)
    params = _params(visit, actor)
    if added:
        notify(User.objects.filter(pk__in=added), NotificationType.VISIT, link=link(visit), actor=actor, message="visit_assigned", params=params)
    if removed:
        notify(User.objects.filter(pk__in=removed), NotificationType.VISIT, link=LINK, actor=actor, message="visit_cancelled", params=params)
    if moved:
        staying = [p for p in _people(visit) if p.pk not in added]
        notify(staying, NotificationType.VISIT, link=link(visit), actor=actor, message="visit_changed", params=params)


def _announce_done(pk, actor_pk):
    """Whoever planned the visit for someone else hears it was done."""
    visit, actor = _load(pk), _user(actor_pk)
    if visit.created_by and visit.created_by_id != visit.assigned_to_id:
        notify(visit.created_by, NotificationType.VISIT, link=link(visit), actor=actor, message="visit_done", params=_params(visit, actor))


def _announce_cancel(pk, actor_pk, was_pending):
    visit, actor = _load(pk), _user(actor_pk)
    people = _people(visit) + ([visit.created_by] if visit.created_by else [])
    if was_pending:
        people += rules.approvers_for(visit.assigned_to)
    notify(people, NotificationType.VISIT, link=LINK, actor=actor, message="visit_cancelled", params=_params(visit, actor))
