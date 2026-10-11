"""Attachment checks: real file type (by content, not the name), size, and image thumbnails.

Allowed: PDF, images (PNG, JPEG, GIF, WebP), Office documents (Word, Excel, PowerPoint, old and
new formats), plain text / CSV, and ZIP. The extension must match what the bytes really are, so a
renamed program or HTML page is refused. SVG is not allowed (it can carry scripts).
"""
import io
import zipfile
from dataclasses import dataclass

from django.core.files.base import ContentFile
from django.utils.translation import gettext as _
from PIL import Image, UnidentifiedImageError

MAX_BYTES = 10 * 1024 * 1024
THUMB_SIZE = (320, 320)

OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # old Office (.doc, .xls, .ppt)
OOXML = {"docx": "word/", "xlsx": "xl/", "pptx": "ppt/"}
MIME = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "doc": "application/msword",
    "xls": "application/vnd.ms-excel",
    "ppt": "application/vnd.ms-powerpoint",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "txt": "text/plain; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
    "zip": "application/zip",
}
ALLOWED_EXTENSIONS = sorted(MIME)
IMAGE_FORMATS = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "gif": "GIF", "webp": "WEBP"}


class FileRejected(ValueError):
    pass


@dataclass
class Checked:
    kind: str  # image | pdf | office | text | zip
    content_type: str
    extension: str


def _is_text(head: bytes) -> bool:
    if b"\x00" in head:
        return False
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            head.decode(encoding)
            return True
        except UnicodeDecodeError:
            # A multi-byte character cut off at the end of the sample is fine.
            try:
                head[:-3].decode(encoding)
                return True
            except UnicodeDecodeError:
                continue
    return False


def check_upload(upload) -> Checked:
    """Raise FileRejected (with a message for the user) unless the file is allowed."""
    name = (upload.name or "").lower()
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    if upload.size > MAX_BYTES:
        raise FileRejected(_("“%(name)s” is too large. Files can be up to 10 MB.") % {"name": upload.name})
    if upload.size == 0:
        raise FileRejected(_("“%(name)s” is empty.") % {"name": upload.name})
    if ext not in MIME:
        raise FileRejected(_("“%(name)s” is not an allowed file type.") % {"name": upload.name})

    upload.seek(0)
    head = upload.read(8192)
    upload.seek(0)
    mismatch = FileRejected(_("“%(name)s” is not really a %(ext)s file.") % {"name": upload.name, "ext": ext.upper()})

    if ext == "pdf":
        if not head.startswith(b"%PDF-"):
            raise mismatch
        return Checked("pdf", MIME[ext], ext)
    if ext in IMAGE_FORMATS:
        try:
            with Image.open(upload) as img:
                fmt = img.format
                img.verify()
        except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
            raise mismatch
        finally:
            upload.seek(0)
        if fmt != IMAGE_FORMATS[ext]:
            raise mismatch
        return Checked("image", MIME[ext], ext)
    if ext in ("doc", "xls", "ppt"):
        if not head.startswith(OLE2):
            raise mismatch
        return Checked("office", MIME[ext], ext)
    if ext in OOXML or ext == "zip":
        if not head.startswith(b"PK\x03\x04"):
            raise mismatch
        try:
            with zipfile.ZipFile(upload) as archive:
                names = archive.namelist()
        except zipfile.BadZipFile:
            raise mismatch
        finally:
            upload.seek(0)
        if ext in OOXML:
            if "[Content_Types].xml" not in names or not any(n.startswith(OOXML[ext]) for n in names):
                raise mismatch
            return Checked("office", MIME[ext], ext)
        return Checked("zip", MIME[ext], ext)
    # txt / csv
    if not _is_text(head):
        raise mismatch
    return Checked("text", MIME[ext], ext)


def make_thumbnail(upload) -> ContentFile | None:
    """A small re-encoded copy (no metadata) for image previews; None if it can't be made."""
    try:
        upload.seek(0)
        with Image.open(upload) as img:
            img.seek(0)  # first frame of an animated GIF
            img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
            img.thumbnail(THUMB_SIZE)
            out = io.BytesIO()
            img.save(out, "WEBP", quality=80)
        return ContentFile(out.getvalue(), name="thumb.webp")
    except Exception:
        return None
    finally:
        upload.seek(0)
