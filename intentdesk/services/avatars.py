"""Turn whatever someone uploaded into a small, safe PNG.

An avatar upload is the one place in this app where a stranger's bytes get
stored and later served back to a browser, so the rules are stricter than the
feature deserves:

1. **Size is checked before decoding.** A 30 MB "PNG" that is really a zip bomb
   should never reach the decoder.
2. **The declared content-type is ignored.** It is attacker-supplied. The magic
   bytes decide, and Pillow's own parse is the final arbiter.
3. **Nothing is stored as uploaded.** The image is decoded, resized, and
   re-encoded. That drops EXIF — phone photos carry GPS coordinates, and a
   sales team's location history is not something to keep by accident — and it
   destroys polyglot files, which rely on bytes outside the image data
   surviving intact.
"""

import io

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
SIDE = 256

# Checked before Pillow is asked to parse anything, so an unrecognised format is
# rejected without invoking a decoder on it at all.
MAGIC = (
    b"\x89PNG\r\n\x1a\n",       # png
    b"\xff\xd8\xff",            # jpeg
    b"RIFF",                    # webp (container; the WEBP tag is at offset 8)
    b"GIF87a",
    b"GIF89a",
)


class AvatarError(Exception):
    """Rejected upload, with a message safe to show the user."""


def normalise(raw: bytes) -> bytes:
    """Validate and re-encode to a square 256x256 PNG.

    Raises AvatarError with something worth reading; never lets a Pillow
    exception escape, because those leak decoder internals into an API response.
    """
    if not raw:
        raise AvatarError("That file is empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise AvatarError("Images must be under 2 MB.")
    if not raw.startswith(MAGIC):
        raise AvatarError("That is not a PNG, JPEG, WebP or GIF.")

    try:
        from PIL import Image, ImageOps
    except ImportError as exc:  # pragma: no cover - deployment error, not user error
        raise AvatarError("Image support is not installed on the server.") from exc

    try:
        with Image.open(io.BytesIO(raw)) as img:
            # Rotates per the EXIF orientation tag before that tag is discarded.
            # Skipping this is why uploaded phone photos so often arrive sideways.
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")
            # Centre-crop to square first: a plain resize would squash a portrait
            # into a circle-cropped avatar and make everyone look wrong.
            img = ImageOps.fit(img, (SIDE, SIDE), method=Image.Resampling.LANCZOS)

            out = io.BytesIO()
            img.save(out, format="PNG", optimize=True)
            return out.getvalue()
    except AvatarError:
        raise
    except Exception as exc:
        raise AvatarError("That image could not be read.") from exc
