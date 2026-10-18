"""Visit reports: how it went, notes, photos and the next action (see models.VisitReport).

- Written by the people who went, their department's managers or admins; writing it marks a planned visit done
  (instead of "Mark done", and without its separate notification).
- Photos follow the task-file rules (real type by content, 10 MB, private storage, random names) and are photos
  only (JPEG, PNG, WebP). Each is re-encoded from its pixels, so EXIF, GPS location and other metadata are never
  kept (consistent with the location rules); the thumbnail is made from the cleaned copy.
- On a contact's, company's or vendor's visit the report is a timeline entry (kind "visit") whose follow-up date
  is the next action's date: the timeline's follow-ups make the task (assigned to the writer or a colleague they
  choose, with the usual rules and notification) and keep it in step. A visit to a place gets the same task
  directly. A contact's lead status can be moved from the report (a normal status change, with its history).
- Whoever planned the visit and the person responsible hear about a new report (not the writer).
"""
import io

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _
from PIL import Image, ImageOps

from apps.core.audit import log_action
from apps.core.models import AuditLog
from apps.core.office_time import office_today
from apps.core.permissions import has_perm
from apps.notifications.models import NotificationType
from apps.notifications.services import notify
from apps.tasks.files import FileRejected, check_upload, make_thumbnail

from . import rules
from .models import Visit, VisitPhoto, VisitReport
from .services import VisitError, _load, _params, link

MAX_PHOTOS = 8
PHOTO_MAX_SIDE = 2560
MAX_PIXELS = 50_000_000  # refuse decompression bombs before decoding
PHOTO_TYPES = {"jpg": ("JPEG", "image/jpeg"), "jpeg": ("JPEG", "image/jpeg"), "png": ("PNG", "image/png"), "webp": ("WEBP", "image/webp")}
FIELDS = ("outcome", "notes", "next_action", "next_action_on")


class NotAllowed(Exception):
    """This person may not write or change this report (not PermissionError: that is also an OS file error)."""


# ================================================================ photos


def clean_photo(upload) -> tuple[ContentFile, dict]:
    """Check a photo (task-file rules) and re-encode it from pixels only: no EXIF, GPS, XMP or trailing data.
    Returns the cleaned file and {width, height, content_type}."""
    name = upload.name or ""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in PHOTO_TYPES:
        raise VisitError({"photos": _("“%(name)s” is not a photo. Photos can be JPEG, PNG or WebP.") % {"name": name}})
    try:
        check_upload(upload)
    except FileRejected as exc:
        raise VisitError({"photos": str(exc)})
    fmt, content_type = PHOTO_TYPES[ext]
    upload.seek(0)
    with Image.open(upload) as probe:
        if probe.size[0] * probe.size[1] > MAX_PIXELS:
            raise VisitError({"photos": _("“%(name)s” is too large to open.") % {"name": name}})
    upload.seek(0)
    with Image.open(upload) as img:
        img = ImageOps.exif_transpose(img)  # keep it upright once the EXIF orientation is gone
        img.thumbnail((PHOTO_MAX_SIDE, PHOTO_MAX_SIDE), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        if fmt == "JPEG":
            img.convert("RGB").save(out, "JPEG", quality=85, optimize=True)
        elif fmt == "PNG":
            img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB").save(out, "PNG", optimize=True)
        else:
            img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB").save(out, "WEBP", quality=85)
        width, height = img.size
    upload.seek(0)
    return ContentFile(out.getvalue(), name=f"photo.{'jpg' if fmt == 'JPEG' else ext}"), {
        "width": width, "height": height, "content_type": content_type,
    }


def _add_photos(report, user, cleaned):
    for (upload, (content, info)) in cleaned:
        photo = VisitPhoto(report=report, original_name=upload.name[:255], size=content.size, uploaded_by=user, **info)
        thumb = make_thumbnail(content)
        photo.file.save(content.name, content, save=False)
        if thumb:
            photo.thumbnail.save("thumb.webp", thumb, save=False)
        photo.save()


# ================================================================ saving


def check_contact_status(user, visit, status) -> bool:
    """May this person move the visited contact's lead status? (contact edit permission and the contact visible)"""
    from apps.contacts.visibility import visible_contacts

    return bool(visit.contact_id and has_perm(user, "contacts", "edit") and visible_contacts(user).filter(pk=visit.contact_id).exists())


def save(user, visit, data: dict, photos=(), remove_photos=(), now=None, announce=True) -> tuple[VisitReport, dict, bool]:
    """Write or change the report. Returns (report, changes for the audit log, created). announce=False: no
    notification about the report (the seed command)."""
    now = now or timezone.now()
    if not rules.can_report(user, visit, now):
        raise NotAllowed
    report = VisitReport.objects.filter(visit=visit).first()
    created = report is None
    next_on, action = data.get("next_action_on"), (data.get("next_action") or "").strip()
    if next_on and not action:
        raise VisitError({"next_action": _("Say what the next action is.")})
    if next_on and next_on < office_today() and (created or next_on != report.next_action_on):
        raise VisitError({"next_action_on": _("The next action can't be in the past.")})
    status = data.get("contact_status") or ""
    if status and visit.contact_id and status != visit.contact.status and not check_contact_status(user, visit, status):
        raise VisitError({"contact_status": _("You can't change this contact's status.")})
    removing = list(report.photos.filter(pk__in=remove_photos)) if report and remove_photos else []
    kept = (report.photos.count() if report else 0) - len(removing)
    if kept + len(photos) > MAX_PHOTOS:
        raise VisitError({"photos": _("A report can have up to %(n)s photos.") % {"n": MAX_PHOTOS}})
    cleaned = [(upload, clean_photo(upload)) for upload in photos]  # all checked before anything is saved

    changes = {}
    with transaction.atomic():
        if visit.status == Visit.Status.PLANNED:
            visit.status, visit.closed_by, visit.closed_at = Visit.Status.DONE, user, now
            visit.save(update_fields=["status", "closed_by", "closed_at", "updated_at"])
            changes["status"] = [Visit.Status.PLANNED, Visit.Status.DONE]
        values = {"outcome": data["outcome"], "notes": (data.get("notes") or "").strip(), "next_action": action, "next_action_on": next_on}
        before_on = None if created else report.next_action_on
        if created:
            report = VisitReport.objects.create(visit=visit, written_by=user, written_at=now, **values)
            changes.update({f: [None, str(v)] for f, v in values.items() if v})
        else:
            for f, v in values.items():
                if getattr(report, f) != v:
                    changes[f] = [str(getattr(report, f) or ""), str(v or "")]
                    setattr(report, f, v)
            report.updated_by = user
            report.save()
        if removing:
            for photo in removing:
                photo.delete()  # the post_delete signal removes the files
            changes["photos_removed"] = [", ".join(p.original_name for p in removing), None]
        if cleaned:
            _add_photos(report, user, cleaned)
            changes["photos_added"] = [None, ", ".join(u.name for u, _c in cleaned)]
        if status and visit.contact_id and status != visit.contact.status:
            report.status_change = _move_lead(user, visit.contact, status, data.get("status_reason") or "", now)
            changes["contact_status"] = [report.status_change.from_status, status]
        date_changed = created or before_on != next_on
        task = _sync_entry(report, user, data.get("follow_up_assignee"), date_changed) if _target(visit) else \
            _sync_place_task(report, user, data.get("follow_up_assignee"), date_changed)
        if task is not None and report.follow_up_task_id != task.pk:
            report.follow_up_task = task
            changes["follow_up_task"] = [None, task.title]
        report.save(update_fields=["entry", "follow_up_task", "status_change", "updated_at"])
        if created and announce:
            pk, actor_pk = visit.pk, user.pk
            transaction.on_commit(lambda: _announce(pk, actor_pk))
    return report, changes, created


def _target(visit) -> bool:
    return bool(visit.contact_id or visit.company_id or visit.vendor_id)


def _move_lead(user, contact, status, reason, now):
    """The same status change as moving the card on the pipeline: history row and audit entry."""
    from apps.contacts.models import ContactStatusChange

    old = contact.status
    contact.status, contact.status_changed_at = status, now
    contact.save(update_fields=["status", "status_changed_at", "updated_at"])
    log_action(user, AuditLog.Action.UPDATE, contact, changes={"status": [old, status]})
    return ContactStatusChange.objects.create(contact=contact, from_status=old, to_status=status, reason=reason.strip()[:300],
                                              changed_by=user, changed_at=now)


def _on_site(visit):
    """When the person responsible was there (their check-in and check-out), if they checked in."""
    check = next((c for c in visit.checks.all() if c.user_id == visit.assigned_to_id), None)
    return [check.checked_in_at.isoformat(), check.checked_out_at.isoformat() if check.checked_out_at else None] if check else None


def entry_details(report) -> dict:
    visit = report.visit
    return {
        "visit_id": visit.pk, "status": Visit.Status.DONE, "purpose": visit.purpose, "title": visit.title,
        "start": visit.start.isoformat(), "end": visit.end.isoformat(), "outcome": report.outcome,
        "next_action": report.next_action, "photos": report.photos.count(), "on_site": _on_site(visit),
    }


def _occurred(visit, now):
    """When it happened on the record's history: when they left (checked out), else when the visit ended."""
    times = [c.checked_out_at for c in visit.checks.all() if c.checked_out_at]
    return max(times) if times else min(visit.end, now)


def _sync_entry(report, user, assignee, date_changed):
    from apps.timeline import follow_ups
    from apps.timeline.models import TimelineEntry

    visit = report.visit
    entry = report.entry
    fields = {"summary": report.notes, "details": entry_details(report), "follow_up_on": report.next_action_on}
    if entry is None:
        entry = TimelineEntry.objects.create(
            kind="visit", contact_id=visit.contact_id, company_id=visit.company_id, vendor_id=visit.vendor_id,
            occurred_at=_occurred(visit, timezone.now()), created_by=report.written_by or user, **fields,
        )
        report.entry = entry
    else:
        for f, v in fields.items():
            setattr(entry, f, v)
        entry.updated_by = user
        entry.save()
    return follow_ups.sync(entry, user, assignee=assignee, date_changed=date_changed)


def _sync_place_task(report, user, assignee, date_changed):
    """A visit to a place has no timeline: the next action becomes a task directly (same rules and notification)."""
    from apps.tasks import schedule
    from apps.tasks.collab import record
    from apps.tasks.models import Task
    from apps.timeline import follow_ups

    task = report.follow_up_task
    if not report.next_action_on:
        return task
    if task is not None:
        if task.status != Task.Status.DONE and task.due_date != report.next_action_on:
            old = task.due_date
            task.due_date = report.next_action_on
            task.save(update_fields=["due_date", "updated_at"])
            record(task, user, "due", old=old.isoformat() if old else None, new=task.due_date.isoformat(), old_time=None, new_time=None)
        return task
    if not date_changed or not has_perm(user, "tasks", "create"):
        return None
    person = follow_ups.check_assignee(user, assignee)
    title = _("Next step after %(visit)s: %(action)s") % {"visit": report.visit.title, "action": report.next_action}
    task = Task.objects.create(title=title[:200], description=report.notes, due_date=report.next_action_on, created_by=user, updated_by=user)
    task.assignees.set([person])
    record(task, user, "created")
    log_action(user, AuditLog.Action.CREATE, task, changes={"title": [None, task.title], "assignees": [None, person.full_name]})
    schedule.notify_assigned(task, [person], user)
    return task


def _announce(pk, actor_pk):
    """Whoever planned the visit and the person responsible hear about the report (not whoever wrote it)."""
    from apps.accounts.models import User

    visit = _load(pk)
    report = VisitReport.objects.get(visit=visit)
    actor = User.objects.get(pk=actor_pk)
    people = {u.pk: u for u in (visit.created_by, visit.assigned_to) if u is not None and u.pk != actor_pk}
    if not people:
        return
    params = {**_params(visit, actor), "outcome": report.outcome, "next_action": report.next_action,
              "next_action_on": report.next_action_on.isoformat() if report.next_action_on else ""}
    notify(list(people.values()), NotificationType.VISIT, link=link(visit), actor=actor, message="visit_reported", params=params)
