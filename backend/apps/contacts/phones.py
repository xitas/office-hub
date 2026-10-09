"""Phone number normalisation for duplicate detection and WhatsApp links.

Numbers are typed in many ways ("0300-1234567", "+92 300 1234567", "0092 300...").
We compare a digits-only international form; local numbers starting with a single
0 are assumed to be Pakistani (country code 92), matching the frontend's wa.me logic.
"""
import re

DEFAULT_COUNTRY_CODE = "92"


def normalize_phone(raw: str | None) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("00"):
        return digits[2:]
    if digits.startswith("0"):
        return DEFAULT_COUNTRY_CODE + digits[1:]
    return digits
