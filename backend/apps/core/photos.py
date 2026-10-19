"""Photos taken out in the field (visit reports, errand proof): the task-file rules, then re-encoded from pixels only.

The task-file checks apply (real type by content, 10 MB), photos only (JPEG, PNG, WebP). Each photo is decoded and
saved again from its pixels, so EXIF, GPS location, camera details, XMP and anything trailing are never kept
(consistent with the location rules); large photos are scaled down. Thumbnails are made from the cleaned copy.
"""
import io

from django.core.files.base import ContentFile
from django.utils.translation import gettext as _
from PIL import Image, ImageOps

from apps.tasks.files import FileRejected, check_upload, make_thumbnail

MAX_SIDE = 2560
MAX_PIXELS = 50_000_000  # refuse decompression bombs before decoding
TYPES = {"jpg": ("JPEG", "image/jpeg"), "jpeg": ("JPEG", "image/jpeg"), "png": ("PNG", "image/png"), "webp": ("WEBP", "image/webp")}


class PhotoRejected(ValueError):
    """A message for the person who sent it."""


def clean_photo(upload) -> tuple[ContentFile, dict]:
    """Returns the cleaned file and {width, height, content_type}; raises PhotoRejected."""
    name = upload.name or ""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in TYPES:
        raise PhotoRejected(_("“%(name)s” is not a photo. Photos can be JPEG, PNG or WebP.") % {"name": name})
    try:
        check_upload(upload)
    except FileRejected as exc:
        raise PhotoRejected(str(exc))
    fmt, content_type = TYPES[ext]
    upload.seek(0)
    with Image.open(upload) as probe:
        if probe.size[0] * probe.size[1] > MAX_PIXELS:
            raise PhotoRejected(_("“%(name)s” is too large to open.") % {"name": name})
    upload.seek(0)
    with Image.open(upload) as img:
        img = ImageOps.exif_transpose(img)  # keep it upright once the EXIF orientation is gone
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
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


def save_photos(make, user, cleaned):
    """Store cleaned photos: make(original_name, size, info) -> an unsaved photo model with file/thumbnail fields."""
    for upload, (content, info) in cleaned:
        photo = make(upload.name[:255], content.size, info)
        photo.uploaded_by = user
        thumb = make_thumbnail(content)
        photo.file.save(content.name, content, save=False)
        if thumb:
            photo.thumbnail.save("thumb.webp", thumb, save=False)
        photo.save()
