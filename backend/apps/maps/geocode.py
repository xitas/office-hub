"""Address search through OpenStreetMap's Nominatim, called only by our backend (never from browsers).

Following the Nominatim usage policy (https://operations.osmfoundation.org/policies/nominatim/):
- at most one request a second for the whole office (a shared slot in the cache; others wait their turn briefly),
- results cached (30 days), so the same search is asked once,
- a User-Agent naming the app with a contact email from settings (NOMINATIM_CONTACT_EMAIL in .env, never in code).
  Without it, search is switched off and nothing is sent.
- searches happen when someone presses Search (no search-as-you-type), and only centre the map; a pin is set by
  dropping it or "use my location".
"""
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

from apps.core.safe_cache import safe_cache

URL = "https://nominatim.openstreetmap.org/search"
CACHE_SECONDS = 30 * 24 * 3600
SLOT_KEY = "nominatim:slot"
WAIT_SECONDS = 3.0  # how long a search waits for the one-a-second slot before giving up
TIMEOUT = 8
LIMIT = 5
MIN_LENGTH = 3


class SearchError(Exception):
    """code: disabled | busy | failed"""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def enabled() -> bool:
    return bool((getattr(settings, "NOMINATIM_CONTACT_EMAIL", "") or "").strip())


def normalise(query: str) -> str:
    return " ".join((query or "").split())[:200]


def _key(query: str, language: str) -> str:
    digest = hashlib.sha256(f"{language}|{query.casefold()}".encode()).hexdigest()[:32]
    return f"nominatim:q:{digest}"


def search(query: str, language: str = "en") -> tuple[list[dict], bool]:
    """Places matching the query: [{name, latitude, longitude, kind}], and whether it came from the cache."""
    query = normalise(query)
    key = _key(query, language)
    cached = safe_cache.get(key)
    if cached is not None:
        return cached, True
    if not enabled():
        raise SearchError("disabled")
    _wait_for_slot()
    results = _fetch(query, language)
    safe_cache.set(key, results, timeout=CACHE_SECONDS)
    return results, False


def _wait_for_slot():
    """One request a second across all users and server processes: whoever adds the key holds the slot for 1 s."""
    deadline = time.monotonic() + WAIT_SECONDS
    while not safe_cache.add(SLOT_KEY, 1, timeout=1):
        if time.monotonic() > deadline:
            raise SearchError("busy")
        time.sleep(0.2)


def user_agent() -> str:
    return f"OfficeCRM/1.0 (address search for an office CRM; contact: {settings.NOMINATIM_CONTACT_EMAIL.strip()})"


def _fetch(query: str, language: str) -> list[dict]:
    params = {"q": query, "format": "jsonv2", "limit": LIMIT, "accept-language": language}
    countries = (getattr(settings, "NOMINATIM_COUNTRY_CODES", "") or "").strip()
    if countries:
        params["countrycodes"] = countries
    request = urllib.request.Request(f"{URL}?{urllib.parse.urlencode(params)}", headers={"User-Agent": user_agent()})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 (fixed https URL)
            rows = json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        raise SearchError("failed")
    out = []
    for row in rows if isinstance(rows, list) else []:
        try:
            out.append({
                "name": str(row.get("display_name", ""))[:300],
                "latitude": round(float(row["lat"]), 6),
                "longitude": round(float(row["lon"]), 6),
                "kind": str(row.get("type") or row.get("category") or ""),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return out
