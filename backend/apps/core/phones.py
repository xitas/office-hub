"""Phone number normalisation for duplicate detection and WhatsApp links.

Numbers are typed in many ways ("0300-1234567", "+92 300 1234567", "0092 300...").
We compare a digits-only international form; local numbers starting with a single
0 are assumed to be Pakistani (country code 92), matching the frontend's wa.me logic.
"""
import re

DEFAULT_COUNTRY_CODE = "92"


def phone_query_variants(query: str) -> list[str]:
    """Digit strings to look for when a search box holds (part of) a phone number in any format.

    "0300-123", "+92 300 123" and "300 123" all find "923001234567". Returns [] for text that isn't
    a phone number (letters, or fewer than 4 digits).
    """
    if not re.fullmatch(r"[+\d\s().\-/]+", query or ""):
        return []
    digits = re.sub(r"\D", "", query)
    if len(digits) < 4:
        return []
    variants = {digits, normalize_phone(query)}
    return sorted(v for v in variants if len(v) >= 4)


def normalize_phone(raw: str | None) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("00"):
        return digits[2:]
    if digits.startswith("0"):
        return DEFAULT_COUNTRY_CODE + digits[1:]
    return digits
