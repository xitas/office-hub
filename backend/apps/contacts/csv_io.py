"""CSV columns, Excel-friendly writing and tolerant reading for contact/company import and export.

Excel details handled here:
- Files start with a UTF-8 BOM, otherwise Excel opens Urdu text as mojibake.
- Phone numbers are written as ="0300 1234567" so Excel keeps them as text (no lost leading
  zero, no 9.23E+11). Import unwraps that form again.
- Cells starting with = + - @ are prefixed with ' so they can't run as formulas (CSV injection).
"""
import codecs
import csv
import io
import re
from dataclasses import dataclass, field

from django.utils import translation
from django.utils.translation import gettext_lazy as _

BOM = codecs.BOM_UTF8.decode()
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000
FORMULA_CHARS = ("=", "+", "-", "@", "\t", "\r")


@dataclass(frozen=True)
class Column:
    key: str
    label: object  # lazy translation
    aliases: tuple[str, ...] = ()
    phone: bool = False
    required: bool = False
    importable: bool = True
    exportable: bool = True
    extra: dict = field(default_factory=dict)


CONTACT_COLUMNS = [
    Column("first_name", _("First name"), ("firstname", "given name", "forename"), required=True),
    Column("last_name", _("Last name"), ("lastname", "surname", "family name")),
    Column("full_name", _("Full name"), ("name", "contact name", "contact"), exportable=False),
    Column("company", _("Company"), ("company name", "organisation", "organization", "business")),
    Column("job_title", _("Job title"), ("title", "designation", "position", "role")),
    Column("phone", _("Phone"), ("phone number", "mobile", "mobile number", "cell", "telephone", "tel", "contact number"), phone=True),
    Column("whatsapp", _("WhatsApp"), ("whatsapp number", "wa"), phone=True),
    Column("email", _("Email"), ("email address", "e-mail", "mail")),
    Column("address", _("Address"), ("street", "street address")),
    Column("city", _("City"), ("town",)),
    Column("tags", _("Tags"), ("tag", "labels", "label")),
    Column("status", _("Lead status"), ("status", "stage", "lead stage")),
    Column("assigned_to", _("Assigned to"), ("owner", "assigned", "assignee", "salesperson", "account manager")),
    Column("created_at", _("Added on"), ("created", "created at", "date added"), importable=False),
]

COMPANY_COLUMNS = [
    Column("name", _("Company name"), ("name", "company", "organisation", "organization", "business"), required=True),
    Column("industry", _("Industry"), ("sector", "business type")),
    Column("phone", _("Phone"), ("phone number", "telephone", "tel", "mobile"), phone=True),
    Column("email", _("Email"), ("email address", "e-mail", "mail")),
    Column("website", _("Website"), ("web", "url", "site")),
    Column("address", _("Address"), ("street", "street address")),
    Column("city", _("City"), ("town",)),
    Column("notes", _("Notes"), ("note", "comments", "remarks")),
    Column("assigned_to", _("Assigned to"), ("owner", "assigned", "assignee", "account manager")),
    Column("contact_count", _("Contacts"), importable=False),
    Column("created_at", _("Added on"), ("created", "created at", "date added"), importable=False),
]

COLUMNS = {"contacts": CONTACT_COLUMNS, "companies": COMPANY_COLUMNS}


def columns_for(kind: str, *, importable=False, exportable=False) -> list[Column]:
    cols = COLUMNS[kind]
    if importable:
        cols = [c for c in cols if c.importable]
    if exportable:
        cols = [c for c in cols if c.exportable]
    return cols


def _norm(text: str) -> str:
    return re.sub(r"[\s_\-./()]+", " ", text.casefold()).strip()


def header_names(column: Column) -> set[str]:
    """Every header that maps to this column: key, aliases, and its label in each UI language."""
    names = {_norm(column.key), *(_norm(a) for a in column.aliases)}
    for lang in ("en", "ur"):
        with translation.override(lang):
            names.add(_norm(str(column.label)))
    return names


def suggest_mapping(kind: str, headers: list[str]) -> dict[str, str]:
    """{"<column index>": field key} for headers we recognise; each field is used once."""
    lookup = {}
    for column in columns_for(kind, importable=True):
        for name in header_names(column):
            lookup.setdefault(name, column.key)
    mapping, used = {}, set()
    for index, header in enumerate(headers):
        key = lookup.get(_norm(header))
        if key and key not in used:
            mapping[str(index)] = key
            used.add(key)
    # "Name" alone means full name for contacts, unless first/last name columns exist too.
    if kind == "contacts" and "full_name" in used and "first_name" in used:
        mapping = {i: k for i, k in mapping.items() if k != "full_name"}
    return mapping


# ---------------------------------------------------------------- writing


def excel_text(value) -> str:
    text = "" if value is None else str(value)
    if text.startswith(FORMULA_CHARS):
        return "'" + text
    return text


def excel_phone(value: str) -> str:
    value = (value or "").replace('"', "").strip()
    return f'="{value}"' if value else ""


class CsvWriter:
    """Builds an Excel-friendly CSV (BOM, CRLF) row by row."""

    def __init__(self, columns: list[Column] | None = None, header: list[str] | None = None):
        self.columns = columns or []
        self.buffer = io.StringIO()
        self.buffer.write(BOM)
        self.writer = csv.writer(self.buffer)
        self.writer.writerow(header if header is not None else [str(c.label) for c in self.columns])

    def row(self, values: dict):
        self.writer.writerow([
            excel_phone(values.get(c.key, "")) if c.phone else excel_text(values.get(c.key, "")) for c in self.columns
        ])

    def raw_row(self, cells: list):
        self.writer.writerow([excel_text(c) for c in cells])

    def getvalue(self) -> str:
        return self.buffer.getvalue()


# ---------------------------------------------------------------- reading


class CsvError(ValueError):
    pass


def clean_cell(value: str) -> str:
    """Undo our own Excel protections and tidy whitespace."""
    value = (value or "").strip()
    match = re.fullmatch(r'="(.*)"', value)
    if match:
        value = match.group(1).strip()
    if value.startswith("'") and value[1:2] in FORMULA_CHARS:
        value = value[1:]
    return value


def decode(data: bytes) -> str:
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Older Excel "CSV (Comma delimited)" files use the Windows code page.
        return data.decode("cp1252", errors="replace")


def read_csv(upload) -> tuple[list[str], list[list[str]]]:
    """Validate an uploaded file and return (headers, data rows). Raises CsvError with a user-facing message."""
    name = (getattr(upload, "name", "") or "").lower()
    if not name.endswith(".csv"):
        raise CsvError(_("Please choose a .csv file. In Excel use File → Save As → CSV UTF-8."))
    if upload.size > MAX_FILE_BYTES:
        raise CsvError(_("The file is too large. The limit is 5 MB."))
    data = upload.read()
    utf16 = data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE))
    if data.startswith(b"PK\x03\x04") or (b"\x00" in data[:4096] and not utf16):
        raise CsvError(_("This looks like an Excel workbook, not a CSV file. Save it as CSV UTF-8 first."))
    text = decode(data)
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    try:
        rows = [row for row in csv.reader(io.StringIO(text), dialect) if any(cell.strip() for cell in row)]
    except csv.Error:
        raise CsvError(_("The file could not be read as CSV."))
    if not rows:
        raise CsvError(_("The file is empty."))
    headers = [h.strip() or str(_("Column %(n)s") % {"n": i + 1}) for i, h in enumerate(rows[0])]
    data_rows = rows[1:]
    if not data_rows:
        raise CsvError(_("The file has a header row but no data."))
    if len(data_rows) > MAX_ROWS:
        raise CsvError(_("The file has %(count)s rows. The limit is %(max)s per import.") % {"count": len(data_rows), "max": MAX_ROWS})
    width = len(headers)
    return headers, [(row + [""] * width)[:width] for row in data_rows]
