"""A3 change (human decision 2026-09-26; FRONTEND_REQUESTS #7, OPEN_QUESTIONS #3; A-B3 superseded
in contract/DECISIONS.md): the visible avatar is the user's real body, cut out of the scan photo
head to feet, on a transparent 1:2 (width:height) canvas -- never the drawn mannequin.

Bug fix (2026-09-27): live webcam scans are landscape (e.g. 1080x608) with the person standing far
back -- a thin strip of the frame. Running the segmenter on the WHOLE frame made the person too
small a fraction of it (< MIN_PERSON_FRACTION), so every live scan fell back. Fixed by segmenting
only the person's own pose bounding box (`pose_bbox`, built from the pose landmarks already
detected for the rig -- head top above the nose, feet below the ankles, padded) instead of the
full frame: the same person is now a large fraction of the region actually analyzed, regardless of
how small they are in the source photo. `MIN_PERSON_FRACTION` is checked against that crop, not
the frame.

The person mask comes from MediaPipe ImageSegmenter's multiclass model (mp_models.image_segmenter
-- the same model A-B5 already uses for skin detection): every non-background category (hair,
body-skin, face-skin, clothes, others). Cleaned with the largest connected component (drops
stray specks the model sometimes classifies elsewhere in the frame), a small bounded morphological
close (fills small holes in the mask -- never the real background between the legs or under an
arm, which stays transparent), and a 1-2px feathered edge (soft alpha, not a hard cutout line).

Fallback (A-B8 spirit, tightened 2026-09-27 -- "no mannequin at all"): if the segmenter itself
fails, or the cleaned mask is implausibly small within the pose bbox, `build_person_cutout`
returns None and the caller (service.build_avatar_visuals) uses `photo_crop_fallback` instead: a
plain crop of the person from the source photo (the same pose bbox), with a soft vignette fading
to transparency at its edges -- a real photo either way, never line art. The drawn wireframe
remains available separately as the render loading state (`wireframe_url`).
"""
from typing import Optional

import cv2
import numpy as np
from PIL import Image

from .mp_models import image_segmenter
from .rig import Rig

# Within the pose-bbox crop (not the whole frame -- see module docstring), below this fraction the
# mask is treated as a failed/implausible segmentation rather than a real person.
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

# The pose landmarks span shoulders/hips/wrists/ankles, not the literal top of the head or the
# tip of the feet -- padded generously (wider than the mask-bbox pad above, since landmarks alone
# undershoot the body's true extent, especially width when arms hang close to the torso).
POSE_BBOX_PAD_W_FRACTION = 0.10
POSE_BBOX_PAD_H_FRACTION = 0.06
FOOT_ALLOWANCE_FRACTION = 0.18  # beyond the ankle landmark, room for the foot/shoe (of shoulder width)

# The segmenter's own model input is 256x256; a pose-bbox crop smaller than this is upscaled
# before segmenting (then the mask is downscaled back), so a distant subject in a landscape frame
# isn't handed to the model at a handful of native pixels.
SEGMENTER_TARGET_DIM = 256


def pose_bbox(
    rig: Rig,
    landmarks_px: dict[str, tuple[float, float, float]],
    frame_size: tuple[int, int],
    pad_w_fraction: float = POSE_BBOX_PAD_W_FRACTION,
    pad_h_fraction: float = POSE_BBOX_PAD_H_FRACTION,
) -> tuple[int, int, int, int]:
    """-> (x0, y0, x1, y1): the person's own head-to-feet region in `landmarks_px`'s pixel
    coordinates, padded and clamped to `frame_size`. This is the region segmentation and the
    photo-crop fallback both operate on -- never the whole frame."""
    pts = {n: (x, y) for n, (x, y, _v) in landmarks_px.items()}
    xs = [p[0] for p in pts.values()]
    ys = [p[1] for p in pts.values()]

    head_top = rig.head_center[1] - rig.head_radius * 1.3  # matches rig.canvas_bbox's own allowance
    y_top = min(min(ys), head_top)

    foot_bottom = max(ys)
    left_ankle, right_ankle = pts.get("left_ankle"), pts.get("right_ankle")
    for ankle in (left_ankle, right_ankle):
        if ankle is not None:
            foot_bottom = max(foot_bottom, ankle[1])
    foot_bottom += rig.shoulder_width * FOOT_ALLOWANCE_FRACTION

    x0, x1 = min(xs), max(xs)
    y0, y1 = y_top, foot_bottom

    pad_x, pad_y = (x1 - x0) * pad_w_fraction, (y1 - y0) * pad_h_fraction
    fw, fh = frame_size
    x0, y0 = max(0, round(x0 - pad_x)), max(0, round(y0 - pad_y))
    x1, y1 = min(fw, round(x1 + pad_x)), min(fh, round(y1 + pad_y))
    return (x0, y0, max(x1, x0 + 1), max(y1, y0 + 1))  # never degenerate


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


def _segment_mask_in_crop(crop_rgb: np.ndarray) -> Optional[np.ndarray]:
    """`_segment_person_mask`, but upscaling a small crop first (see SEGMENTER_TARGET_DIM) and
    mapping the resulting mask back to the crop's own original size."""
    ch, cw = crop_rgb.shape[:2]
    scale = SEGMENTER_TARGET_DIM / max(ch, cw) if max(ch, cw) < SEGMENTER_TARGET_DIM else 1.0

    source = crop_rgb
    if scale > 1.0:
        source = cv2.resize(
            crop_rgb, (round(cw * scale), round(ch * scale)), interpolation=cv2.INTER_LANCZOS4,
        )

    mask = _segment_person_mask(source)
    if mask is None:
        return None
    if scale > 1.0:
        mask = cv2.resize(mask.astype(np.uint8), (cw, ch), interpolation=cv2.INTER_NEAREST) > 0
    return mask


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


def build_person_cutout(
    rgb: np.ndarray, bbox: tuple[int, int, int, int],
) -> Optional[tuple[Image.Image, tuple[int, int, int, int]]]:
    """Segments only within `bbox` (see `pose_bbox`) -- not the whole frame.
    -> (rgba_crop, full_frame_bbox) where full_frame_bbox = (x0, y0, x1, y1) is the crop's
    location back in `rgb`'s own pixel coordinates, or None when the mask fails or is implausible
    (the caller then uses `photo_crop_fallback` -- never the drawn mannequin).
    """
    bx0, by0, bx1, by1 = bbox
    crop = rgb[by0:by1, bx0:bx1]

    mask = _segment_mask_in_crop(crop)
    if mask is None or mask.sum() < MIN_PERSON_FRACTION * mask.size:
        return None

    cleaned = _largest_component(mask)
    cleaned = _close_small_holes(cleaned)
    if cleaned.sum() < MIN_PERSON_FRACTION * cleaned.size:
        return None

    tight = _mask_bbox(cleaned, BBOX_PAD_FRACTION, (crop.shape[1], crop.shape[0]))
    if tight is None:
        return None
    tx0, ty0, tx1, ty1 = tight

    alpha = _feather(cleaned)
    rgba = np.dstack([crop[ty0:ty1, tx0:tx1], alpha[ty0:ty1, tx0:tx1]])
    full_bbox = (bx0 + tx0, by0 + ty0, bx0 + tx1, by0 + ty1)
    return Image.fromarray(rgba, mode="RGBA"), full_bbox


def _vignette_alpha(size: tuple[int, int], inset_fraction: float = 0.04, blur_fraction: float = 0.06) -> np.ndarray:
    """-> uint8 alpha (0-255): opaque in the interior, softly fading to transparent near the
    crop's own edges -- used only for the no-mannequin photo-crop fallback, never a hard
    rectangle."""
    w, h = size
    alpha = np.zeros((h, w), dtype=np.uint8)
    inset_x, inset_y = round(w * inset_fraction), round(h * inset_fraction)
    alpha[inset_y:max(inset_y + 1, h - inset_y), inset_x:max(inset_x + 1, w - inset_x)] = 255
    k = max(3, round(min(w, h) * blur_fraction))
    if k % 2 == 0:
        k += 1
    return cv2.GaussianBlur(alpha, (k, k), 0)


def photo_crop_fallback(rgb: np.ndarray, bbox: tuple[int, int, int, int]) -> Image.Image:
    """Never fails, never line art: a plain crop of the person from the source photo (`bbox` --
    see `pose_bbox`), vignetted to transparency at its edges instead of a hard cutout."""
    x0, y0, x1, y1 = bbox
    crop = rgb[y0:y1, x0:x1]
    alpha = _vignette_alpha((crop.shape[1], crop.shape[0]))
    rgba = np.dstack([crop, alpha])
    return Image.fromarray(rgba, mode="RGBA")


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
