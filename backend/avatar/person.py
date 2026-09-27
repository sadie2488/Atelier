"""A3 change (human decision 2026-09-26; FRONTEND_REQUESTS #7, OPEN_QUESTIONS #3; A-B3 superseded
in contract/DECISIONS.md): the visible avatar is the user's real body, cut out of the scan photo
head to feet, on a transparent 1:2 (width:height) canvas -- not the drawn mannequin.

The person mask comes from MediaPipe ImageSegmenter's multiclass model (mp_models.image_segmenter
-- the same model A-B5 already uses for skin detection): every non-background category (hair,
body-skin, face-skin, clothes, others). Cleaned with the largest connected component (drops
stray specks the model sometimes classifies elsewhere in the frame), a small bounded morphological
close (fills small holes in the mask -- never the real background between the legs or under an
arm, which stays transparent), and a 1-2px feathered edge (soft alpha, not a hard cutout line).

Fallback (A-B8 spirit): if the segmenter itself fails, or the cleaned mask is implausibly small
(< MIN_PERSON_FRACTION of the frame -- a failed or near-empty segmentation), this returns None and
the caller (service.build_avatar_visuals) falls back to today's drawn avatar. A scan must never
fail over this.
"""
from typing import Optional

import cv2
import numpy as np
from PIL import Image

from .mp_models import image_segmenter

# Below this fraction of the frame, the mask is treated as a failed/implausible segmentation
# rather than a real (if small) person -- falls back to the drawn avatar (A-B8).
MIN_PERSON_FRACTION = 0.05

# Crop padding beyond the mask's own bounding box, as a fraction of that box's width/height --
# mirrors the P0.7 artifact spec's 2% cutout padding; small margin only, no extra art direction.
BBOX_PAD_FRACTION = 0.03

# Bounded hole closing: fills small gaps (a stray unclassified pixel inside the silhouette)
# without ever bridging real background regions (between the legs, under a raised arm), which
# are much larger than this kernel.
HOLE_CLOSE_FRACTION = 0.01

# Target width:height for the avatar canvas (1:2), so the frontend can fit the avatar by height
# without cropping it.
CANVAS_RATIO = 0.5


def _segment_person_mask(rgb: np.ndarray) -> Optional[np.ndarray]:
    """-> bool (h, w) mask of every non-background category, or None if segmentation itself
    fails (model load/download failure, or the task raising on this input)."""
    import mediapipe as mp

    try:
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        result = image_segmenter().segment(mp_image)
        category_mask = result.category_mask.numpy_view()
    except Exception:
        return None

    # The real model returns (h, w, 1); a test double may return the bare (h, w) already.
    if category_mask.ndim == 3:
        category_mask = category_mask[..., 0]
    return category_mask != 0  # 0 == background (see mp_models.image_segmenter's category list)


def _largest_component(mask: np.ndarray) -> np.ndarray:
    mask_u8 = mask.astype(np.uint8) * 255
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask_u8, connectivity=8)
    if num_labels <= 1:  # nothing but background
        return mask
    areas = stats[1:, cv2.CC_STAT_AREA]
    largest_label = 1 + int(np.argmax(areas))
    return labels == largest_label


def _close_small_holes(mask: np.ndarray) -> np.ndarray:
    h, w = mask.shape
    k = max(3, round(min(h, w) * HOLE_CLOSE_FRACTION))
    if k % 2 == 0:
        k += 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    mask_u8 = mask.astype(np.uint8) * 255
    closed = cv2.morphologyEx(mask_u8, cv2.MORPH_CLOSE, kernel)
    return closed > 0


def _feather(mask: np.ndarray) -> np.ndarray:
    """-> uint8 alpha (0-255) with a ~1-2px soft edge instead of mask's hard boundary."""
    alpha = mask.astype(np.float32) * 255.0
    blurred = cv2.GaussianBlur(alpha, (5, 5), sigmaX=0.9)
    return np.clip(blurred, 0, 255).astype(np.uint8)


def _mask_bbox(
    mask: np.ndarray, pad_fraction: float, frame_size: tuple[int, int],
) -> Optional[tuple[int, int, int, int]]:
    ys, xs = np.where(mask)
    if xs.size == 0:
        return None
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    w, h = frame_size
    pad_x = round((x1 - x0) * pad_fraction)
    pad_y = round((y1 - y0) * pad_fraction)
    return (max(0, x0 - pad_x), max(0, y0 - pad_y), min(w, x1 + pad_x), min(h, y1 + pad_y))


def build_person_cutout(rgb: np.ndarray) -> Optional[tuple[Image.Image, tuple[int, int, int, int]]]:
    """-> (rgba_crop, bbox) where bbox = (x0, y0, x1, y1) is the crop's location in `rgb`'s own
    pixel coordinates (post-padding), or None when the mask fails or is implausible.
    """
    h, w = rgb.shape[:2]
    mask = _segment_person_mask(rgb)
    if mask is None or mask.sum() < MIN_PERSON_FRACTION * mask.size:
        return None

    cleaned = _largest_component(mask)
    cleaned = _close_small_holes(cleaned)
    if cleaned.sum() < MIN_PERSON_FRACTION * cleaned.size:
        return None

    bbox = _mask_bbox(cleaned, BBOX_PAD_FRACTION, (w, h))
    if bbox is None:
        return None
    x0, y0, x1, y1 = bbox

    alpha_full = _feather(cleaned)
    rgba = np.dstack([rgb[y0:y1, x0:x1], alpha_full[y0:y1, x0:x1]])
    return Image.fromarray(rgba, mode="RGBA"), bbox


def pad_to_ratio(crop_img: Image.Image, ratio: float = CANVAS_RATIO) -> tuple[Image.Image, tuple[int, int]]:
    """-> (canvas_img, (offset_x, offset_y)): `crop_img` centered on a transparent canvas grown
    (never cropped) in whichever dimension is needed to reach width:height == ratio."""
    cw, ch = crop_img.size
    if cw / ch <= ratio:
        canvas_w, canvas_h = max(cw, round(ch * ratio)), ch
    else:
        canvas_w, canvas_h = cw, max(ch, round(cw / ratio))
    offset = (round((canvas_w - cw) / 2), round((canvas_h - ch) / 2))
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    canvas.alpha_composite(crop_img.convert("RGBA"), offset)
    return canvas, offset
