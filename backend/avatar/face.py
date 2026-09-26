"""A-B6: the real face is composited at the head. Cropped via MediaPipe face detection,
background removed, scaled to the wireframe's neck anchor (done by draw.draw_avatar).
"""
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .mp_models import face_detector


def detect_face_box(rgb: np.ndarray) -> Optional[tuple[int, int, int, int]]:
    """-> (x0, y0, x1, y1) pixel box of the largest detected face, or None."""
    import mediapipe as mp

    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
    result = face_detector().detect(mp_image)
    if not result.detections:
        return None
    best = max(result.detections, key=lambda d: d.bounding_box.width * d.bounding_box.height)
    bb = best.bounding_box
    return (bb.origin_x, bb.origin_y, bb.origin_x + bb.width, bb.origin_y + bb.height)


def crop_face(rgb: np.ndarray, box: tuple[int, int, int, int], pad_fraction: float = 0.35) -> Image.Image:
    """Crop the face with padding and remove the background with a soft elliptical alpha mask.

    Not full segmentation -- that model is not a dependency of this lane. A soft ellipse is
    enough for a small circular head cutout to read as intentional rather than a clipped
    rectangle (A-B6, "background removed").
    """
    h, w = rgb.shape[:2]
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    px, py = bw * pad_fraction, bh * pad_fraction
    cx0, cy0 = max(0, int(x0 - px)), max(0, int(y0 - py))
    cx1, cy1 = min(w, int(x1 + px)), min(h, int(y1 + py))
    crop = Image.fromarray(rgb[cy0:cy1, cx0:cx1]).convert("RGBA")

    mask = Image.new("L", crop.size, 0)
    draw = ImageDraw.Draw(mask)
    inset_x, inset_y = crop.width * 0.06, crop.height * 0.02
    draw.ellipse([inset_x, inset_y, crop.width - inset_x, crop.height - inset_y], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=max(2, crop.width // 40)))
    crop.putalpha(mask)
    return crop
