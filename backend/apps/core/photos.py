"""Images people upload, made safe to keep: upright, and without EXIF, GPS location, camera details or other metadata.

- Photos taken out in the field (visit reports, errand proof): the task-file rules, JPEG, PNG or WebP only, re-encoded
  from their pixels (and scaled down when large) by clean_photo().
- Every other image that's stored (task, chat and announcement attachments, expense receipts, resource photos):
  prepare_upload() checks the file (apps.tasks.files) and, for images, clean_image() turns it upright by its
  orientation tag and saves it again in the same format and size without metadata: JPEGs with their own quantization
  tables and subsampling (so their quality stays as it was), PNGs losslessly with their palette and transparency,
  WebPs lossless if they were, animated GIFs with all their frames. The colour profile (ICC) is kept: it isn't
  identifying, and dropping it would change the colours. Other files (PDF, Office, ZIP, text) are stored as uploaded.
- Thumbnails are made from the cleaned copy, upright.
- `manage.py clean_stored_images` does the same to images stored before this existed.
"""
import io
from dataclasses import dataclass

from django.core.files.base import ContentFile
from django.utils.translation import gettext as _
from PIL import Image, ImageOps, JpegImagePlugin

from apps.tasks.files import IMAGE_FORMATS, Checked, FileRejected, check_upload, make_thumbnail

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


# ================================================================ images kept at full size (attachments, receipts…)

# Metadata an image file can carry about where, when and with what it was taken (or anything else).
METADATA_KEYS = ("exif", "xmp", "XML:com.adobe.xmp", "comment", "photoshop", "iptc", "mp", "mpinfo")
ORIENTATION = 0x0112


def needs_cleaning(img) -> bool:
    """Whether an opened image still carries metadata, or an orientation tag that isn't "upright"."""
    if img.getexif() or any(img.info.get(k) for k in METADATA_KEYS):
        return True
    return bool(getattr(img, "text", None)) or img.format == "MPO"  # PNG text chunks; a phone JPEG's extra images


def _webp_lossless(head: bytes) -> bool:
    return head[12:16] == b"VP8L" or (head[12:16] == b"VP8X" and b"VP8L" in head[:4096] and b"VP8 " not in head[:4096])


def clean_image(source, ext: str) -> ContentFile:
    """The image upright and without metadata, in the same format and size; raises FileRejected if it can't be read."""
    fmt = IMAGE_FORMATS[ext]
    source.seek(0)
    head = source.read(4096)
    source.seek(0)
    out = io.BytesIO()
    try:
        with Image.open(source) as img:
            if img.size[0] * img.size[1] > MAX_PIXELS:
                raise FileRejected(_("“%(name)s” is too large to open.") % {"name": getattr(source, "name", "")})
            icc = img.info.get("icc_profile")
            keep = {"icc_profile": icc} if icc else {}
            if fmt == "GIF":
                frames = getattr(img, "n_frames", 1)
                for key in METADATA_KEYS:
                    img.info.pop(key, None)
                options = {k: img.info[k] for k in ("loop", "transparency", "background") if k in img.info}
                if frames > 1:  # each frame's own timing and disposal
                    durations, disposals = [], []
                    for k in range(frames):
                        img.seek(k)
                        durations.append(img.info.get("duration", 0))
                        disposals.append(getattr(img, "disposal_method", 0))
                    img.seek(0)
                    options.update(duration=durations, disposal=disposals)
                elif "duration" in img.info:
                    options["duration"] = img.info["duration"]
                img.save(out, "GIF", save_all=frames > 1, comment=b"", **options)
            elif fmt == "WEBP" and getattr(img, "n_frames", 1) > 1:  # animated: every frame, no metadata
                options = {"lossless": True} if _webp_lossless(head) else {"quality": 90}
                img.save(out, "WEBP", save_all=True, **options, **keep)
            else:
                img.seek(0)  # an MPO (phone JPEG with extra images): its main picture only
                quantization = getattr(img, "quantization", None)
                sampling = JpegImagePlugin.get_sampling(img) if fmt == "JPEG" else -1
                transparency = img.info.get("transparency")
                upright = ImageOps.exif_transpose(img)
                upright.info = {}  # nothing of the original's metadata may be written again
                if fmt == "JPEG":
                    options = {"qtables": quantization} if quantization else {"quality": 95}
                    if sampling != -1:
                        options["subsampling"] = sampling
                    upright.save(out, "JPEG", optimize=True, **options, **keep)
                elif fmt == "PNG":
                    if transparency is not None:
                        keep["transparency"] = transparency
                    upright.save(out, "PNG", **keep)
                else:
                    options = {"lossless": True} if _webp_lossless(head) else {"quality": 90}
                    upright.save(out, "WEBP", **options, **keep)
    except FileRejected:
        raise
    except Exception:
        raise FileRejected(_("“%(name)s” could not be read as an image.") % {"name": getattr(source, "name", "")})
    finally:
        source.seek(0)
    return ContentFile(out.getvalue(), name=f"upload.{ext}")


@dataclass
class Prepared:
    """An upload ready to store: what to write (the cleaned image, or the file as uploaded), its size and thumbnail."""

    upload: object
    info: Checked
    content: object
    size: int
    thumbnail: ContentFile | None


def prepare_upload(upload) -> Prepared:
    """Check an upload (raises FileRejected) and, for an image, clean it and make its thumbnail. Call it for every file
    before storing any, so a refused file leaves nothing behind."""
    info = check_upload(upload)
    if info.kind != "image":
        return Prepared(upload, info, upload, upload.size, None)
    content = clean_image(upload, info.extension)
    return Prepared(upload, info, content, content.size, make_thumbnail(content))
