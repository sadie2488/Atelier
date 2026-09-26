"""Image in -> EXIF-corrected, long side IMAGE_LONG_SIDE_PX, gray-world white balanced RGB array."""
import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from contract.enums import IMAGE_LONG_SIDE_PX

# Cap gray-world gains so a garment that fills the frame (e.g. a red top) isn't neutralized.
MAX_WB_GAIN = 1.25


def load_image(src: bytes | str | Path | Image.Image) -> Image.Image:
    if isinstance(src, Image.Image):
        img = src
    elif isinstance(src, bytes):
        img = Image.open(io.BytesIO(src))
    else:
        img = Image.open(src)
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, rgba)
    return img.convert("RGB")


def resize_long_side(img: Image.Image, long_side: int = IMAGE_LONG_SIDE_PX) -> Image.Image:
    w, h = img.size
    scale = long_side / max(w, h)
    return img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)


def gray_world(rgb: np.ndarray) -> np.ndarray:
    px = rgb.astype(np.float64)
    means = px.reshape(-1, 3).mean(axis=0)
    gains = np.clip(means.mean() / np.maximum(means, 1e-6), 1 / MAX_WB_GAIN, MAX_WB_GAIN)
    return np.clip(px * gains, 0, 255).round().astype(np.uint8)


def preprocess(src: bytes | str | Path | Image.Image) -> np.ndarray:
    """Returns an HxWx3 uint8 RGB array."""
    img = resize_long_side(load_image(src))
    return gray_world(np.asarray(img))
