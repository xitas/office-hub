"""Placeholders in template subjects and bodies, and the links that send the filled text.

{contact.first_name}, {my.phone}, {today}, ... are replaced with values from the chosen contact,
the person using the template and the organization. Anything else in braces that looks like a
placeholder is reported as unknown; a known placeholder with no value (a contact without a
company) becomes empty and is reported, so people can fix the text before sending it.
"""
import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import quote

from django.utils.translation import gettext_lazy as _

PLACEHOLDER_RE = re.compile(r"\{([a-z_]+(?:\.[a-z_]+)?)\}")


@dataclass(frozen=True)
class Placeholder:
    key: str
    label: str
    value: Callable  # (contact or None, user) -> str
    example: str = ""


def _contact(attr):
    def get(contact, user):
        return (getattr(contact, attr, "") or "") if contact else ""

    return get


def _today(contact, user):
    from apps.core.models import OrganizationSettings
    from apps.core.office_time import office_today

    day = office_today()
    formats = {"DD/MM/YYYY": "%d/%m/%Y", "MM/DD/YYYY": "%m/%d/%Y", "YYYY-MM-DD": "%Y-%m-%d", "DD MMM YYYY": "%d %b %Y"}
    return day.strftime(formats.get(OrganizationSettings.cached().date_format, "%d/%m/%Y"))


def _org_name(contact, user):
    from apps.core.models import OrganizationSettings

    return OrganizationSettings.cached().org_name or ""


PLACEHOLDERS = [
    Placeholder("contact.first_name", _("Contact's first name"), _contact("first_name"), "Ali"),
    Placeholder("contact.last_name", _("Contact's last name"), _contact("last_name"), "Khan"),
    Placeholder("contact.full_name", _("Contact's full name"), _contact("full_name"), "Ali Khan"),
    Placeholder("contact.job_title", _("Contact's job title"), _contact("job_title"), "Purchase Manager"),
    Placeholder("contact.company", _("Contact's company"), lambda c, u: c.company.name if c and c.company else "", "Clifton Retail"),
    Placeholder("contact.phone", _("Contact's phone"), _contact("phone"), "0300 1234567"),
    Placeholder("contact.email", _("Contact's email"), _contact("email"), "ali@example.com"),
    Placeholder("contact.city", _("Contact's city"), _contact("city"), "Lahore"),
    Placeholder("my.name", _("My full name"), lambda c, u: u.full_name, "Hamza Raza"),
    Placeholder("my.first_name", _("My first name"), lambda c, u: u.full_name.split(" ")[0], "Hamza"),
    Placeholder("my.phone", _("My phone"), lambda c, u: u.phone, "0321 7654321"),
    Placeholder("my.email", _("My email"), lambda c, u: u.email, "hamza@office.test"),
    Placeholder("my.job_title", _("My job title"), lambda c, u: u.job_title, "Sales Executive"),
    Placeholder("org.name", _("Our organization's name"), _org_name, "Our Office"),
    Placeholder("today", _("Today's date"), _today, "13/10/2026"),
]
BY_KEY = {p.key: p for p in PLACEHOLDERS}


@dataclass
class Filled:
    text: str
    unknown: list[str]
    empty: list[str]


def fill(text: str, contact, user) -> Filled:
    """Replace placeholders. Unknown ones stay as written; known ones without a value become empty."""
    unknown: list[str] = []
    empty: list[str] = []

    def replace(match):
        key = match.group(1)
        placeholder = BY_KEY.get(key)
        if placeholder is None:
            if key not in unknown:
                unknown.append(key)
            return match.group(0)
        value = str(placeholder.value(contact, user) or "").strip()
        if not value and key not in empty:
            empty.append(key)
        return value

    return Filled(PLACEHOLDER_RE.sub(replace, text or ""), unknown, empty)


def check(text: str) -> list[str]:
    """Unknown placeholders in a text (for the editor), in order of appearance."""
    seen: list[str] = []
    for match in PLACEHOLDER_RE.finditer(text or ""):
        key = match.group(1)
        if key not in BY_KEY and key not in seen:
            seen.append(key)
    return seen


# ================================================================ links


def whatsapp_number(phone: str) -> str:
    """International digits for wa.me: local Pakistani 03xx numbers become 923xx (same rule as the app)."""
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("00"):
        return digits[2:]
    if digits.startswith("0"):
        return "92" + digits[1:]
    return digits


def whatsapp_link(phone: str, text: str) -> str | None:
    """wa.me link that opens a chat with the message typed in (UTF-8, line breaks kept)."""
    number = whatsapp_number(phone)
    if not number:
        return None
    return f"https://wa.me/{number}?text={quote(text, safe='')}"


def mailto_link(email: str, subject: str, body: str) -> str | None:
    """mailto link with subject and body; line breaks are CRLF as mail apps expect (RFC 6068)."""
    if not email:
        return None
    body = body.replace("\r\n", "\n").replace("\n", "\r\n")
    return f"mailto:{quote(email, safe='@')}?subject={quote(subject, safe='')}&body={quote(body, safe='')}"
