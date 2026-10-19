"""Asking for, giving out, taking, doing and cancelling errands, and the "due soon" reminder (see models.py)."""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import photos
from apps.leave.rules import approvers_for
from apps.notifications.models import NotificationType
from apps.notifications.services import notify

from . import rules
from .models import Errand, ErrandPhoto, ErrandUpdate

LINK = "/errands"
TARGETS = ("contact", "company", "vendor")
WATCHED = ("due_at", "place_name", "address", "city", "contact", "company", "vendor", "latitude", "longitude")
REMINDER_LEAD = timedelta(minutes=60)
MAX_PHOTOS = 6


class ErrandError(ValueError):
    """{field: message}"""

    def __init__(self, errors: dict):
        self.errors = errors
        super().__init__(next(iter(errors.values())))


class NotAllowed(Exception):
    pass


def link(errand) -> str:
    return f"{LINK}?errand={errand.pk}"


def _step(errand, status, user, note="", at=None):
    ErrandUpdate.objects.create(errand=errand, status=status, note=note[:500], by=user, at=at or timezone.now())


def check(user, data: dict, department_id):
    if sum(1 for t in TARGETS if data.get(t)) > 1:
        raise ErrandError({"contact": _("Choose one: a contact, a company or a vendor.")})
    if not any(data.get(t) for t in TARGETS) and not (data.get("place_name") or "").strip() and not (data.get("address") or "").strip():
        raise ErrandError({"place_name": _("Say where the errand is.")})
    if (data.get("latitude") is None) != (data.get("longitude") is None):
        raise ErrandError({"latitude": _("Give both latitude and longitude, or neither.")})
    runner = data.get("assigned_to")
    if runner is not None and not rules.can_run(user, runner, department_id):
        raise ErrandError({"assigned_to": _("Errands go to someone in the department.")})


def create(user, data: dict) -> Errand:
    check(user, data, user.department_id)
    if data.get("due_at") and data["due_at"] < timezone.now() - timedelta(hours=1):
        raise ErrandError({"due_at": _("The time it's due can't be in the past.")})
    runner = data.get("assigned_to")
    with transaction.atomic():
        errand = Errand.objects.create(**data, department_id=user.department_id, requested_by=user,
                                       status=Errand.Status.ASSIGNED if runner else Errand.Status.OPEN)
        _step(errand, Errand.Status.OPEN, user)
        if runner:
            _step(errand, Errand.Status.ASSIGNED, user, runner.full_name)
        pk, actor_pk = errand.pk, user.pk
        transaction.on_commit(lambda: _announce_new(pk, actor_pk))
    return errand


def change(user, errand, data: dict) -> dict:
    """Change an errand that isn't finished; returns {field: [old, new]} for the audit log."""
    if not rules.can_change(user, errand):
        raise NotAllowed
    merged = {f: getattr(errand, f) for f in (*WATCHED, "assigned_to", "title", "kind", "details", "task")}
    merged.update(data)
    check(user, merged, errand.department_id)
    if errand.status == Errand.Status.ON_THE_WAY and "assigned_to" in data and data["assigned_to"] != errand.assigned_to:
        raise ErrandError({"assigned_to": _("They're already on the way; cancel it instead.")})
    old_runner = errand.assigned_to
    changes = {}
    with transaction.atomic():
        for field, value in data.items():
            before = getattr(errand, field)
            if before != value:
                changes[field] = [str(before or ""), str(value or "")]
                setattr(errand, field, value)
        if "assigned_to" in changes:
            errand.status = Errand.Status.ASSIGNED if errand.assigned_to else Errand.Status.OPEN
            _step(errand, errand.status, user, errand.assigned_to.full_name if errand.assigned_to else "")
        errand.save()
        moved = any(f in changes for f in WATCHED)
        pk, actor_pk, old_pk = errand.pk, user.pk, old_runner.pk if old_runner else None
        transaction.on_commit(lambda: _announce_change(pk, actor_pk, old_pk, "assigned_to" in changes, moved))
    return changes


def take(user, errand) -> Errand:
    if not rules.can_take(user, errand):
        raise NotAllowed
    errand.assigned_to, errand.status = user, Errand.Status.ASSIGNED
    errand.save(update_fields=["assigned_to", "status", "updated_at"])
    _step(errand, Errand.Status.ASSIGNED, user, user.full_name)
    pk, actor_pk = errand.pk, user.pk
    transaction.on_commit(lambda: _tell_requester(pk, actor_pk, "errand_taken"))
    return errand


def start(user, errand) -> Errand:
    if not rules.can_progress(user, errand) or errand.status != Errand.Status.ASSIGNED:
        raise NotAllowed
    errand.status, errand.started_at = Errand.Status.ON_THE_WAY, timezone.now()
    errand.save(update_fields=["status", "started_at", "updated_at"])
    _step(errand, errand.status, user)
    pk, actor_pk = errand.pk, user.pk
    transaction.on_commit(lambda: _tell_requester(pk, actor_pk, "errand_started"))
    return errand


def finish(user, errand, *, done: bool, note="", reference="", files=()) -> Errand:
    """Done (with a note, a reference and proof photos) or not done (saying why)."""
    if not rules.can_progress(user, errand):
        raise NotAllowed
    note = note.strip()
    if not done and not note:
        raise ErrandError({"note": _("Say why it couldn't be done.")})
    if errand.photos.count() + len(files) > MAX_PHOTOS:
        raise ErrandError({"photos": _("Up to %(n)s photos.") % {"n": MAX_PHOTOS}})
    try:
        cleaned = [(f, photos.clean_photo(f)) for f in files]
    except photos.PhotoRejected as exc:
        raise ErrandError({"photos": str(exc)})
    with transaction.atomic():
        errand.status = Errand.Status.DONE if done else Errand.Status.FAILED
        errand.finished_at, errand.outcome_note = timezone.now(), note[:500]
        if reference.strip():
            errand.reference = reference.strip()[:100]
        errand.save(update_fields=["status", "finished_at", "outcome_note", "reference", "updated_at"])
        photos.save_photos(lambda name, size, info: ErrandPhoto(errand=errand, original_name=name, size=size, **info), user, cleaned)
        _step(errand, errand.status, user, note)
        pk, actor_pk = errand.pk, user.pk
        transaction.on_commit(lambda: _tell_requester(pk, actor_pk, "errand_done" if done else "errand_failed"))
    return errand


def cancel(user, errand, note="") -> Errand:
    if not rules.can_change(user, errand):
        raise NotAllowed
    errand.status, errand.outcome_note = Errand.Status.CANCELLED, note.strip()[:500]
    errand.save(update_fields=["status", "outcome_note", "updated_at"])
    _step(errand, errand.status, user, note)
    pk, actor_pk = errand.pk, user.pk
    transaction.on_commit(lambda: _announce_cancel(pk, actor_pk))
    return errand


def send_reminders(now=None) -> int:
    """Errands due within the hour: the runner is reminded once per due time."""
    now = now or timezone.now()
    due = Errand.objects.filter(status__in=[Errand.Status.ASSIGNED, Errand.Status.ON_THE_WAY], due_at__gt=now,
                                due_at__lte=now + REMINDER_LEAD).select_related("assigned_to", "contact", "company", "vendor")
    sent = 0
    for errand in due:
        if errand.reminded_due == errand.due_at:
            continue
        if not Errand.objects.filter(pk=errand.pk).exclude(reminded_due=errand.due_at).update(reminded_due=errand.due_at):
            continue  # another run got there first
        notify(errand.assigned_to, NotificationType.ERRAND, link=link(errand), message="errand_due", params=_params(errand))
        sent += 1
    return sent


# ================================================================ notifications


def _load(pk):
    return Errand.objects.select_related("assigned_to", "requested_by", "contact", "company", "vendor").get(pk=pk)


def _user(pk):
    from apps.accounts.models import User

    return User.objects.get(pk=pk) if pk else None


def _params(errand, actor=None) -> dict:
    return {
        "title": errand.title, "kind": errand.kind, "place": errand.place,
        "address": ", ".join(x for x in (errand.address, errand.city) if x),
        "due": errand.due_at.isoformat() if errand.due_at else "",
        "runner": errand.assigned_to.full_name if errand.assigned_to else "",
        "requester": errand.requested_by.full_name if errand.requested_by else "",
        "actor": actor.full_name if actor else "", "note": errand.outcome_note, "reference": errand.reference,
    }


def _send(people, errand, actor, message):
    people = [p for p in people if p is not None and (actor is None or p.pk != actor.pk)]
    if people:
        notify(people, NotificationType.ERRAND, link=link(errand), actor=actor, message=message, params=_params(errand, actor))


def _announce_new(pk, actor_pk):
    """The runner hears it's theirs; an open errand goes to the department's managers (admins when there are none)."""
    errand, actor = _load(pk), _user(actor_pk)
    if errand.assigned_to:
        _send([errand.assigned_to], errand, actor, "errand_assigned")
    else:
        _send(approvers_for(actor), errand, actor, "errand_open")


def _announce_change(pk, actor_pk, old_pk, runner_changed, moved):
    errand, actor = _load(pk), _user(actor_pk)
    if runner_changed:
        if old_pk:
            _send([_user(old_pk)], errand, actor, "errand_reassigned")
        if errand.assigned_to:
            _send([errand.assigned_to], errand, actor, "errand_assigned")
    elif moved and errand.assigned_to:
        _send([errand.assigned_to], errand, actor, "errand_changed")


def _tell_requester(pk, actor_pk, message):
    errand = _load(pk)
    _send([errand.requested_by], errand, _user(actor_pk), message)


def _announce_cancel(pk, actor_pk):
    errand = _load(pk)
    _send([errand.assigned_to, errand.requested_by], errand, _user(actor_pk), "errand_cancelled")
