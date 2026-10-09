"""Row-by-row CSV import of contacts or companies, shared by the preview, the inline run and the Celery task.

Each row goes through the same serializers as the API, so assignment rules (staff → themselves,
managers → their department), company visibility, tags and status history behave exactly as when
a record is added by hand. Rows are saved one at a time in their own transaction: a bad row
fails on its own and never undoes the others.
"""
import logging
import re
from dataclasses import dataclass, field
from types import SimpleNamespace

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q
from django.utils import timezone, translation
from django.utils.translation import gettext as _
from django.utils.translation import gettext_noop

from apps.accounts.models import User
from apps.core.audit import log_action
from apps.core.models import AuditLog

from .csv_io import clean_cell, columns_for
from .models import Company, Contact, ContactImport
from .phones import normalize_phone
from .serializers import MAX_TAGS, CompanySerializer, ContactSerializer
from .visibility import visible_companies, visible_contacts

logger = logging.getLogger(__name__)

PREVIEW_ROWS = 10
PROGRESS_EVERY = 25
DUPLICATE_MODES = ("skip", "update", "create")
PHONE_RE = re.compile(r"[+\d\s().\-/]+")

CREATE, UPDATE, SKIP, FAIL = "create", "update", "skip", "fail"


@dataclass
class RowResult:
    line: int
    values: dict
    outcome: str = CREATE
    messages: list[str] = field(default_factory=list)


def _choices_lookup(choices) -> dict[str, str]:
    """Accept a choice by key or by its label in English or Urdu, ignoring case."""
    lookup = {}
    for key, label in choices:
        lookup[key.casefold()] = key
        for lang in ("en", "ur"):
            with translation.override(lang):
                lookup[str(label).casefold()] = key
    return lookup


def _split_tags(text: str) -> list[str]:
    separator = ";" if ";" in text else ","
    return [t.strip() for t in text.split(separator) if t.strip()]


def _flatten_errors(errors, labels: dict) -> list[str]:
    messages = []
    for key, value in errors.items():
        items = value if isinstance(value, list) else [value]
        label = labels.get(key)
        for item in items:
            text = str(item)
            messages.append(f"{label}: {text}" if label else text)
    return messages


class Importer:
    def __init__(self, job: ContactImport, user):
        self.job = job
        self.user = user
        self.kind = job.kind
        self.columns = {c.key: c for c in columns_for(self.kind, importable=True)}
        self.mapping = {int(i): key for i, key in (job.mapping or {}).items() if key in self.columns}
        options = job.options or {}
        self.duplicates = options.get("duplicates", "skip")
        self.create_companies = bool(options.get("create_companies", True))
        self.default_assignee = self._user_by_id(options.get("assign_to")) or user
        self.context = {"request": SimpleNamespace(user=user)}
        self.labels = {key: str(c.label) for key, c in self.columns.items()}
        self.labels.setdefault("non_field_errors", "")
        self._users = None
        self._companies: dict[str, Company] = {}  # created during this run, by casefolded name
        self.status_lookup = _choices_lookup(Contact.Status.choices)
        self.industry_lookup = _choices_lookup(Company.Industry.choices)

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _user_by_id(user_id):
        if not user_id:
            return None
        return User.objects.filter(pk=user_id, is_active=True).first()

    def _find_user(self, text: str):
        """Assigned person by email or full name (active users only). Returns (user, error)."""
        if self._users is None:
            self._users = list(User.objects.filter(is_active=True))
        needle = text.casefold()
        by_email = [u for u in self._users if u.email.casefold() == needle]
        if by_email:
            return by_email[0], None
        by_name = [u for u in self._users if u.full_name.casefold() == needle]
        if len(by_name) == 1:
            return by_name[0], None
        if len(by_name) > 1:
            return None, _("More than one person is called “%(name)s”. Use their email instead.") % {"name": text}
        return None, _("Unknown person “%(name)s”.") % {"name": text}

    def values(self, row: list[str]) -> dict:
        return {key: clean_cell(row[index]) for index, key in self.mapping.items() if index < len(row)}

    def _check_phone(self, value: str, label: str, messages: list):
        digits = re.sub(r"\D", "", value)
        if not PHONE_RE.fullmatch(value) or not 7 <= len(digits) <= 15:
            messages.append(_("%(field)s “%(value)s” doesn’t look like a phone number.") % {"field": label, "value": value})

    def _check_email(self, value: str, messages: list):
        try:
            validate_email(value)
        except DjangoValidationError:
            messages.append(_("“%(value)s” is not a valid email address.") % {"value": value})

    def _assignee(self, values: dict, messages: list):
        """(user id or None for "leave as is", given explicitly?)"""
        text = values.get("assigned_to", "")
        if not text:
            return None, False
        user, error = self._find_user(text)
        if error:
            messages.append(error)
        return (user.pk if user else None), True

    # ------------------------------------------------------------ contacts

    def _contact_row(self, line: int, row: list[str], commit: bool) -> RowResult:
        values = self.values(row)
        result = RowResult(line, values)
        msgs = result.messages

        first, last = values.get("first_name", ""), values.get("last_name", "")
        if not first and values.get("full_name"):
            first, _sep, rest = values["full_name"].partition(" ")
            last = last or rest.strip()
        if not first:
            msgs.append(_("First name is required."))
        for key in ("phone", "whatsapp"):
            if values.get(key):
                self._check_phone(values[key], self.labels[key], msgs)
        if values.get("email"):
            self._check_email(values["email"], msgs)
        status = ""
        if values.get("status"):
            status = self.status_lookup.get(values["status"].casefold(), "")
            if not status:
                msgs.append(_("Unknown lead status “%(value)s”.") % {"value": values["status"]})
        tags = _split_tags(values.get("tags", ""))
        if len(tags) > MAX_TAGS:
            msgs.append(_("Too many tags (the limit is %(max)s).") % {"max": MAX_TAGS})
        assignee, assignee_given = self._assignee(values, msgs)

        company, new_company = None, ""
        company_name = values.get("company", "")
        if company_name:
            company = self._companies.get(company_name.casefold()) or (
                visible_companies(self.user).filter(name__iexact=company_name).order_by("pk").first()
            )
            if company is None:
                if Company.objects.filter(name__iexact=company_name).exists():
                    msgs.append(_("Company “%(name)s” belongs to someone else, so contacts can’t be linked to it.") % {"name": company_name})
                elif self.create_companies:
                    new_company = company_name
                else:
                    msgs.append(_("Company “%(name)s” not found.") % {"name": company_name})
        if msgs:
            result.outcome = FAIL
            return result

        payload = {
            k: v for k, v in {
                "first_name": first, "last_name": last, "job_title": values.get("job_title", ""),
                "phone": values.get("phone", ""), "whatsapp": values.get("whatsapp", ""), "email": values.get("email", ""),
                "address": values.get("address", ""), "city": values.get("city", ""), "status": status,
            }.items() if v
        }
        if company is not None:
            payload["company"] = company.pk
        if tags:
            payload["tags"] = tags

        existing = self._duplicate(values, result)
        if result.outcome == SKIP:
            return result
        if existing is not None:
            payload["tags"] = sorted({*existing.tags.values_list("name", flat=True), *tags}, key=str.casefold)
            if assignee_given:
                payload["assigned_to"] = assignee
            serializer = ContactSerializer(existing, data=payload, partial=True, context=self.context)
            result.outcome = UPDATE
        else:
            payload["assigned_to"] = assignee if assignee_given else self.default_assignee.pk
            serializer = ContactSerializer(data=payload, context=self.context)
        if new_company:
            msgs.append(_("New company “%(name)s” will be created.") % {"name": new_company})

        if not serializer.is_valid():
            result.outcome = FAIL
            result.messages = _flatten_errors(serializer.errors, self.labels)
            return result
        if not commit:
            return result

        with transaction.atomic():
            if new_company:
                company = self._create_company(new_company, serializer.validated_data.get("assigned_to"), result)
                if company is None:
                    return result
                serializer.validated_data["company"] = company
            if existing is not None:
                serializer.save(updated_by=self.user)
            else:
                contact = serializer.save(created_by=self.user, updated_by=self.user)
                self._imported_entry(contact=contact)
        if new_company:
            self._companies[new_company.casefold()] = company
        return result

    def _duplicate(self, values: dict, result: RowResult):
        """Apply the duplicate option. Returns the contact to update, or None (create / already skipped)."""
        numbers = {n for n in (normalize_phone(values.get("phone")), normalize_phone(values.get("whatsapp"))) if len(n) >= 7}
        email = values.get("email", "")
        match = Q()
        if numbers:
            match |= Q(phone_digits__in=numbers) | Q(whatsapp_digits__in=numbers)
        if email:
            match |= Q(email__iexact=email)
        if not match or self.duplicates == "create":
            return None
        matches = list(Contact.objects.filter(match).order_by("pk")[:10])
        if not matches:
            return None
        visible = list(visible_contacts(self.user).filter(pk__in=[c.pk for c in matches]).order_by("pk"))
        if self.duplicates == "update" and visible:
            result.messages.append(_("Updates %(name)s.") % {"name": visible[0].full_name})
            return visible[0]
        result.outcome = SKIP
        if visible:
            result.messages.append(_("Already in the CRM as %(name)s.") % {"name": visible[0].full_name})
        else:
            result.messages.append(_("Already in the CRM, assigned to someone else."))
        return None

    def _create_company(self, name: str, assignee, result: RowResult):
        serializer = CompanySerializer(
            data={"name": name, "assigned_to": assignee.pk if assignee else None}, context=self.context
        )
        if not serializer.is_valid():
            result.outcome = FAIL
            result.messages = _flatten_errors(serializer.errors, {"name": self.labels.get("company", "")})
            transaction.set_rollback(True)
            return None
        company = serializer.save(created_by=self.user, updated_by=self.user)
        self._imported_entry(company=company)
        return company

    # ------------------------------------------------------------ companies

    def _company_row(self, line: int, row: list[str], commit: bool) -> RowResult:
        values = self.values(row)
        result = RowResult(line, values)
        msgs = result.messages
        name = values.get("name", "")
        if not name:
            msgs.append(_("Company name is required."))
        if values.get("phone"):
            self._check_phone(values["phone"], self.labels["phone"], msgs)
        if values.get("email"):
            self._check_email(values["email"], msgs)
        industry = ""
        if values.get("industry"):
            industry = self.industry_lookup.get(values["industry"].casefold(), "")
            if not industry:
                msgs.append(_("Unknown industry “%(value)s”.") % {"value": values["industry"]})
        assignee, assignee_given = self._assignee(values, msgs)
        if msgs:
            result.outcome = FAIL
            return result

        payload = {
            k: v for k, v in {
                "name": name, "industry": industry, "phone": values.get("phone", ""), "email": values.get("email", ""),
                "website": values.get("website", ""), "address": values.get("address", ""),
                "city": values.get("city", ""), "notes": values.get("notes", ""),
            }.items() if v
        }
        existing = None
        if self.duplicates != "create" and Company.objects.filter(name__iexact=name).exists():
            existing = visible_companies(self.user).filter(name__iexact=name).order_by("pk").first()
            if self.duplicates == "skip" or existing is None:
                result.outcome = SKIP
                msgs.append(
                    _("Already in the CRM as %(name)s.") % {"name": existing.name} if existing
                    else _("Already in the CRM, assigned to someone else.")
                )
                return result
            msgs.append(_("Updates %(name)s.") % {"name": existing.name})
        if existing is not None:
            payload.pop("name")  # matched by name (ignoring case); keep the existing spelling
            if assignee_given:
                payload["assigned_to"] = assignee
            serializer = CompanySerializer(existing, data=payload, partial=True, context=self.context)
            result.outcome = UPDATE
        else:
            payload["assigned_to"] = assignee if assignee_given else self.default_assignee.pk
            serializer = CompanySerializer(data=payload, context=self.context)
        if not serializer.is_valid():
            result.outcome = FAIL
            result.messages = _flatten_errors(serializer.errors, self.labels)
            return result
        if commit:
            with transaction.atomic():
                if existing is not None:
                    serializer.save(updated_by=self.user)
                else:
                    self._imported_entry(company=serializer.save(created_by=self.user, updated_by=self.user))
        return result

    # ------------------------------------------------------------ running

    def _imported_entry(self, **target):
        from apps.timeline.models import TimelineEntry

        TimelineEntry.objects.create(
            kind="imported", summary=self.job.file_name, details={"import": self.job.pk},
            created_by=self.user, updated_by=self.user, **target,
        )

    def process(self, line: int, row: list[str], commit: bool) -> RowResult:
        handler = self._contact_row if self.kind == ContactImport.Kind.CONTACTS else self._company_row
        return handler(line, row, commit)

    def preview(self, limit=PREVIEW_ROWS) -> list[dict]:
        return [
            {"line": i + 2, "values": r.values, "outcome": r.outcome, "messages": r.messages}
            for i, row in enumerate(self.job.rows[:limit])
            for r in [self.process(i + 2, row, commit=False)]
        ]

    def run(self):
        job = self.job
        counts = {CREATE: 0, UPDATE: 0, SKIP: 0, FAIL: 0}
        issues = []
        ContactImport.objects.filter(pk=job.pk).update(status=ContactImport.Status.RUNNING, started_at=timezone.now())
        for i, row in enumerate(job.rows):
            line = i + 2  # line 1 is the header
            try:
                result = self.process(line, row, commit=True)
            except Exception:  # one broken row must not stop the rest
                logger.exception("Import %s: line %s failed", job.pk, line)
                result = RowResult(line, {}, FAIL, [_("Unexpected error while saving this row.")])
            counts[result.outcome] += 1
            if result.outcome in (SKIP, FAIL):
                issues.append({
                    "line": line,
                    "outcome": "skipped" if result.outcome == SKIP else "failed",
                    "reason": " ".join(result.messages),
                    "values": row,
                })
            if (i + 1) % PROGRESS_EVERY == 0:
                ContactImport.objects.filter(pk=job.pk).update(processed_rows=i + 1)

        job.created_count, job.updated_count = counts[CREATE], counts[UPDATE]
        job.skipped_count, job.failed_count = counts[SKIP], counts[FAIL]
        job.processed_rows = len(job.rows)
        job.issues = issues
        job.rows = []  # not needed any more; issues keep the original values of skipped/failed rows
        job.status = ContactImport.Status.DONE
        job.finished_at = timezone.now()
        job.save()
        log_action(
            self.user, AuditLog.Action.IMPORT, job,
            changes={
                "file": job.file_name, "rows": job.total_rows, "created": job.created_count,
                "updated": job.updated_count, "skipped": job.skipped_count, "failed": job.failed_count,
            },
            description=(
                gettext_noop("Imported contacts from a CSV file") if job.kind == ContactImport.Kind.CONTACTS
                else gettext_noop("Imported companies from a CSV file")
            ),
        )
        return job


def run_import(job_id: int):
    """Entry point for the inline run and the Celery task."""
    job = ContactImport.objects.select_related("created_by").get(pk=job_id)
    try:
        with translation.override(job.options.get("language") or "en"):
            return Importer(job, job.created_by).run()
    except Exception as exc:
        logger.exception("Import %s failed", job_id)
        ContactImport.objects.filter(pk=job_id).update(
            status=ContactImport.Status.FAILED, error=str(exc)[:500], finished_at=timezone.now()
        )
        raise
