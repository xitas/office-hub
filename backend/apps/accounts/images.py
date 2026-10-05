"""Profile photo validation and sanitising.

Uploads are decoded with Pillow (the extension and Content-Type are not trusted),
limited to JPEG/PNG/WebP and 2 MB, then re-encoded from pixels only: this drops
EXIF (including GPS location), ICC/XMP blobs and any trailing payload, and
resizes large photos. The stored file gets a random name.
"""
import io
import uuid

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils.translation import gettext as _
from PIL import Image, ImageOps, UnidentifiedImageError
from rest_framework import serializers

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_PIXELS = 40_000_000  # refuse decompression bombs before decoding
MAX_DIMENSION = 512  # avatars are shown at <= 64px; 512 covers high-DPI screens
ALLOWED_FORMATS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}


def process_avatar(upload) -> SimpleUploadedFile:
    if upload.size > MAX_UPLOAD_BYTES:
        raise serializers.ValidationError(_("The photo must be 2 MB or smaller."))

    try:
        upload.seek(0)
        probe = Image.open(upload)
        fmt = probe.format
        width, height = probe.size
        probe.verify()  # structural check; the image must be reopened afterwards
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
        raise serializers.ValidationError(_("Upload a valid image. Allowed formats: JPEG, PNG or WebP."))

    if fmt not in ALLOWED_FORMATS:
        raise serializers.ValidationError(_("Upload a valid image. Allowed formats: JPEG, PNG or WebP."))
    if width * height > MAX_PIXELS:
        raise serializers.ValidationError(_("The photo's dimensions are too large."))

    upload.seek(0)
    image = Image.open(upload)
    image = ImageOps.exif_transpose(image)  # keep the photo upright once EXIF orientation is gone
    image.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)

    out = io.BytesIO()
    if fmt == "JPEG":
        image.convert("RGB").save(out, "JPEG", quality=85, optimize=True)
    elif fmt == "PNG":
        if image.mode not in ("RGB", "RGBA", "L", "LA"):
            image = image.convert("RGBA")
        image.save(out, "PNG", optimize=True)
    else:
        image.save(out, "WEBP", quality=85)

    name = f"{uuid.uuid4().hex}.{ALLOWED_FORMATS[fmt]}"
    return SimpleUploadedFile(name, out.getvalue(), content_type=f"image/{ALLOWED_FORMATS[fmt].replace('jpg', 'jpeg')}")
