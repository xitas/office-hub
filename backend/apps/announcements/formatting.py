"""Light formatting for announcement bodies, stored as plain text:

    **bold**                    bold text
    - item  /  * item           bullet list
    1. item                     numbered list
    [text](https://…)           link (http, https or mailto only)
    https://… / www.…           bare links

The browser draws it (never as HTML, so nothing can be injected). Emails, notifications and
previews use plain_text(), which drops the markers and spells links out.
"""
import re

LINK = re.compile(r"\[([^\]\n]{1,200})\]\(([^)\s]{1,500})\)")
BOLD = re.compile(r"\*\*(.+?)\*\*")
SAFE_SCHEMES = ("http://", "https://", "mailto:")


def unsafe_links(body: str) -> list[str]:
    """Link targets that aren't http(s) or mailto (e.g. javascript:)."""
    return [url for _text, url in LINK.findall(body) if not url.lower().startswith(SAFE_SCHEMES)]


def plain_text(body: str) -> str:
    """The body as readable plain text: no ** markers, links as "text (url)", list markers kept."""

    def link(m):
        text, url = m.group(1), m.group(2)
        return text if text == url else f"{text} ({url.removeprefix('mailto:')})"

    text = LINK.sub(link, body)
    text = BOLD.sub(r"\1", text)
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n")).strip()


def preview(body: str, length: int = 160) -> str:
    """A single-line beginning of the body for notifications and the dashboard."""
    flat = " ".join(re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", line) for line in plain_text(body).split("\n") if line.strip())
    return flat if len(flat) <= length else flat[: length - 1].rstrip() + "…"
