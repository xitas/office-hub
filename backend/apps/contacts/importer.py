"""Row-by-row CSV import of contacts or companies, shared by the preview, the inline run and the Celery task.

Each row goes through the same serializers as the API, so assignment rules (staff → themselves,
managers → their department), company visibility, tags and status history behave exactly as when
a record is added by hand. Rows are saved one at a time in their own transaction: a bad row
fails on its own and never undoes the others.

"Update" never overwrites: it only fills fields that are empty on the existing record and adds
tags. Names, lead status and anything already filled in are left as they are.

Row messages are stored as codes (see import_messages) and translated when shown.
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
from django.utils.translation import gettext_noop

from apps.accounts.models import User
from apps.core.audit import log_action
from apps.core.models import AuditLog

from .csv_io import clean_cell, columns_for
from .import_messages import msg, render_all
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

# Fields "update" may fill in when they are empty on the existing record (names and status never change).
CONTACT_FILLABLE = ("job_title", "phone", "whatsapp", "email", "address", "city")
COMPANY_FILLABLE = ("industry", "phone", "email", "website", "address", "city", "notes")
# Cells that are looked up or split, not saved as typed (their length limit doesn't apply).
NOT_STORED_AS_TYPED = {"status", "industry", "assigned_to", "company", "tags", "full_name"}


@dataclass
class RowResult:
    line: int
    values: dict
    outcome: str = CREATE
    messages: list[dict] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)  # fields an update fills in


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


def _error_messages(errors, field_keys) -> list[dict]:
    """Serializer errors (validated in English) as storable messages."""
    out = []
    for key, value in errors.items():
        for item in value if isinstance(value, list) else [value]:
            if key in field_keys:
                out.append(msg("field_error", field=key, text=str(item)))
            else:
                out.append(msg("error", text=str(item)))
    return out


def _max_lengths(model) -> dict[str, int]:
    return {f.name: f.max_length for f in model._meta.concrete_fields if getattr(f, "max_length", None)}


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
        self._users = None
        self._companies: dict[str, Company] = {}  # created during this run, by casefolded name
        self.status_lookup = _choices_lookup(Contact.Status.choices)
        self.industry_lookup = _choices_lookup(Company.Industry.choices)
        self.max_lengths = _max_lengths(Contact if self.kind == ContactImport.Kind.CONTACTS else Company)

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _user_by_id(user_id):
        if not user_id:
            return None
        return User.objects.filter(pk=user_id, is_active=True).first()

    def _find_user(self, text: str):
        """Assigned person by email or full name (active users only). Returns (user, error message)."""
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
            return None, msg("person_ambiguous", name=text)
        return None, msg("person_unknown", name=text)

    def values(self, row: list[str]) -> dict:
        return {key: clean_cell(row[index]) for index, key in self.mapping.items() if index < len(row)}

    def _check_common(self, values: dict, msgs: list, phone_keys):
        for key in phone_keys:
            value = values.get(key)
            if value:
                digits = re.sub(r"\D", "", value)
                if not PHONE_RE.fullmatch(value) or not 7 <= len(digits) <= 15:
                    msgs.append(msg("bad_phone", field=key, value=value))
        if values.get("email"):
            try:
                validate_email(values["email"])
            except DjangoValidationError:
                msgs.append(msg("bad_email", value=values["email"]))
        for key, value in values.items():
            limit = self.max_lengths.get(key)
            if limit and value and len(value) > limit and key not in phone_keys and key not in NOT_STORED_AS_TYPED:
                msgs.append(msg("too_long", field=key, max=limit))

    def _assignee(self, values: dict, msgs: list):
        """(user id or None, given explicitly in the row?)"""
        text = values.get("assigned_to", "")
        if not text:
            return None, False
        user, error = self._find_user(text)
        if error:
            msgs.append(error)
        return (user.pk if user else None), True

    def _validate(self, serializer, result: RowResult) -> bool:
        # Validate in English so stored errors can be translated for whoever reads them later.
        with translation.override("en"):
            valid = serializer.is_valid()
        if not valid:
            result.outcome = FAIL
            result.messages = _error_messages(serializer.errors, self.columns)
            result.changes = []
        return valid

    @staticmethod
    def _fills(existing, values: dict, fields) -> list[str]:
        return [k for k in fields if values.get(k) and not getattr(existing, k)]

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
            msgs.append(msg("first_name_required"))
        self._check_common({**values, "first_name": first, "last_name": last}, msgs, ("phone", "whatsapp"))
        status = ""
        if values.get("status"):
            status = self.status_lookup.get(values["status"].casefold(), "")
            if not status:
                msgs.append(msg("unknown_status", value=values["status"]))
        tags = _split_tags(values.get("tags", ""))
        if len(tags) > MAX_TAGS:
            msgs.append(msg("too_many_tags", max=MAX_TAGS))
        assignee, assignee_given = self._assignee(values, msgs)

        company, new_company = None, ""
        company_name = values.get("company", "")
        if company_name:
            company = self._companies.get(company_name.casefold()) or (
                visible_companies(self.user).filter(name__iexact=company_name).order_by("pk").first()
            )
            if company is None:
                if Company.objects.filter(name__iexact=company_name).exists():
                    msgs.append(msg("company_hidden", name=company_name))
                elif self.create_companies:
                    new_company = company_name
                else:
                    msgs.append(msg("company_not_found", name=company_name))
        if msgs:
            result.outcome = FAIL
            return result

        existing = self._duplicate(values, result)
        if result.outcome == SKIP:
            return result

        if existing is not None:
            # Fill in what's missing; never rename, re-status or reassign an existing contact.
            fills = self._fills(existing, values, CONTACT_FILLABLE)
            payload = {k: values[k] for k in fills}
            if existing.company_id is None and (company is not None or new_company):
                fills.append("company")
                if company is not None:
                    payload["company"] = company.pk
            else:
                new_company = ""
            if existing.assigned_to_id is None and assignee_given and assignee:
                fills.append("assigned_to")
                payload["assigned_to"] = assignee
            have = {t.casefold() for t in existing.tags.values_list("name", flat=True)}
            new_tags = [t for t in dict.fromkeys(tags) if t.casefold() not in have]
            if new_tags:
                payload["tags"] = [*existing.tags.values_list("name", flat=True), *new_tags]
            if not fills and not new_tags:
                result.outcome = SKIP
                result.messages = [msg("nothing_new", name=existing.full_name)]
                return result
            result.outcome = UPDATE
            result.changes = fills + (["tags"] if new_tags else [])
            if fills:
                msgs.append(msg("fills", fields=fills))
            if new_tags:
                msgs.append(msg("adds_tags", tags=new_tags))
            serializer = ContactSerializer(existing, data=payload, partial=True, context=self.context)
        else:
            payload = {
                k: v for k, v in {
                    "first_name": first, "last_name": last, "job_title": values.get("job_title", ""),
                    "phone": values.get("phone", ""), "whatsapp": values.get("whatsapp", ""),
                    "email": values.get("email", ""), "address": values.get("address", ""),
                    "city": values.get("city", ""), "status": status,
                }.items() if v
            }
            if company is not None:
                payload["company"] = company.pk
            if tags:
                payload["tags"] = tags
            payload["assigned_to"] = assignee if assignee_given else self.default_assignee.pk
            serializer = ContactSerializer(data=payload, context=self.context)
        if new_company:
            msgs.append(msg("company_created", name=new_company))

        if not self._validate(serializer, result) or not commit:
            return result

        with transaction.atomic():
            if new_company:
                assigned = serializer.validated_data.get("assigned_to") or (existing.assigned_to if existing else None)
                company = self._create_company(new_company, assigned, result)
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
            result.messages.append(msg("updates", name=visible[0].full_name))
            return visible[0]
        result.outcome = SKIP
        result.messages.append(msg("duplicate", name=visible[0].full_name) if visible else msg("duplicate_hidden"))
        return None

    def _create_company(self, name: str, assignee, result: RowResult):
        serializer = CompanySerializer(
            data={"name": name, "assigned_to": assignee.pk if assignee else None}, context=self.context
        )
        with translation.override("en"):
            valid = serializer.is_valid()
        if not valid:
            result.outcome = FAIL
            result.messages = _error_messages({"company": serializer.errors.get("name", serializer.errors)}, self.columns)
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
            msgs.append(msg("company_name_required"))
        self._check_common(values, msgs, ("phone",))
        industry = ""
        if values.get("industry"):
            industry = self.industry_lookup.get(values["industry"].casefold(), "")
            if not industry:
                msgs.append(msg("unknown_industry", value=values["industry"]))
        assignee, assignee_given = self._assignee(values, msgs)
        if msgs:
            result.outcome = FAIL
            return result

        cleaned = {**values, "industry": industry}
        existing = None
        if self.duplicates != "create" and Company.objects.filter(name__iexact=name).exists():
            existing = visible_companies(self.user).filter(name__iexact=name).order_by("pk").first()
            if self.duplicates == "skip" or existing is None:
                result.outcome = SKIP
                msgs.append(msg("duplicate", name=existing.name) if existing else msg("duplicate_hidden"))
                return result
            msgs.append(msg("updates", name=existing.name))
        if existing is not None:
            fills = self._fills(existing, cleaned, COMPANY_FILLABLE)
            payload = {k: cleaned[k] for k in fills}
            if existing.assigned_to_id is None and assignee_given and assignee:
                fills.append("assigned_to")
                payload["assigned_to"] = assignee
            if not fills:
                result.outcome = SKIP
                result.messages = [msg("nothing_new", name=existing.name)]
                return result
            result.outcome = UPDATE
            result.changes = fills
            msgs.append(msg("fills", fields=fills))
            serializer = CompanySerializer(existing, data=payload, partial=True, context=self.context)
        else:
            payload = {
                k: v for k, v in {
                    "name": name, "industry": industry, "phone": values.get("phone", ""), "email": values.get("email", ""),
                    "website": values.get("website", ""), "address": values.get("address", ""),
                    "city": values.get("city", ""), "notes": values.get("notes", ""),
                }.items() if v
            }
            payload["assigned_to"] = assignee if assignee_given else self.default_assignee.pk
            serializer = CompanySerializer(data=payload, context=self.context)
        if not self._validate(serializer, result) or not commit:
            return result
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
        """First rows as they would be imported, with messages in the reader's language."""
        rows = []
        for i, row in enumerate(self.job.rows[:limit]):
            r = self.process(i + 2, row, commit=False)
            rows.append({"line": r.line, "values": r.values, "outcome": r.outcome, "changes": r.changes, "messages": render_all(r.messages)})
        return rows

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
                result = RowResult(line, {}, FAIL, [msg("unexpected")])
            counts[result.outcome] += 1
            if result.outcome in (SKIP, FAIL):
                issues.append({
                    "line": line,
                    "outcome": "skipped" if result.outcome == SKIP else "failed",
                    "messages": result.messages,
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
        return Importer(job, job.created_by).run()
    except Exception as exc:
        logger.exception("Import %s failed", job_id)
        ContactImport.objects.filter(pk=job_id).update(
            status=ContactImport.Status.FAILED, error=str(exc)[:500], finished_at=timezone.now()
        )
        raise
