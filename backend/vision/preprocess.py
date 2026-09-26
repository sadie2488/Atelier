"""V1 intake: raw upload bytes -> EXIF-correct RGB array, ready for segmentation.

JPEG/PNG/WebP up to 12 MB (V-E5). A PNG that already carries alpha has it discarded and is
composited onto white before processing.
"""
import io

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from contract.enums import IMAGE_LONG_SIDE_PX, MAX_UPLOAD_BYTES, ErrorCode

from . import VisionError

_ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


def load_and_normalize(data: bytes) -> np.ndarray:
    """Bytes -> HxWx3 uint8 RGB array, EXIF-corrected, long side capped at IMAGE_LONG_SIDE_PX."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise VisionError(
            ErrorCode.invalid_request,
            f"Image is {len(data)} bytes; the limit is {MAX_UPLOAD_BYTES} bytes.",
        )
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise VisionError(ErrorCode.unsupported_image, f"Could not decode image: {e}") from e

    if img.format not in _ALLOWED_FORMATS:
        raise VisionError(
            ErrorCode.unsupported_image,
            f"Unsupported image format {img.format!r}; accepted: JPEG, PNG, WebP.",
        )

    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, rgba)
    img = img.convert("RGB")

    w, h = img.size
    scale = IMAGE_LONG_SIDE_PX / max(w, h)
    if scale < 1.0:
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)

    return np.asarray(img)
