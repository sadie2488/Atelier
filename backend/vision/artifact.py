"""V3 normalization: mask -> RGBA cutout on the P0.7 canvas, plus landmark-normalized anchors.

contract/ARTIFACT_SPEC.md (frozen): crop to the alpha bounding box plus 2% padding on every
side, then scale so the long side is at most IMAGE_LONG_SIDE_PX. No fixed canvas size.
Anchors are normalized to the cutout's own coordinates (x = px / width, y = py / height),
computed from the *pre-scale* crop box -- the ratio is scale-invariant, so no separate
scale-tracking is needed.
"""
import numpy as np
from PIL import Image

from contract.enums import ErrorCode, GarmentType, IMAGE_LONG_SIDE_PX

from . import VisionError
from .candidate_params import CROP_PAD_FRACTION
from .segmentation import ANCHOR_LANDMARKS


def build_cutout(
    rgb: np.ndarray,
    mask: np.ndarray,
    landmarks_px: dict[str, tuple[float, float]],
    garment_type: GarmentType,
) -> tuple[np.ndarray, dict[str, list[float]]]:
    """-> (HxWx4 uint8 RGBA cutout, {anchor_name: [x, y]} normalized to the cutout)."""
    h, w = mask.shape
    ys, xs = np.where(mask)
    if xs.size == 0 or ys.size == 0:
        raise VisionError(ErrorCode.analyze_failed, "Candidate mask is empty; nothing to cut out.")

    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    bw, bh = x1 - x0, y1 - y0
    pad_x = max(1, round(bw * CROP_PAD_FRACTION))
    pad_y = max(1, round(bh * CROP_PAD_FRACTION))

    cx0, cy0 = max(0, x0 - pad_x), max(0, y0 - pad_y)
    cx1, cy1 = min(w, x1 + pad_x), min(h, y1 + pad_y)
    crop_w, crop_h = cx1 - cx0, cy1 - cy0

    alpha = (mask.astype(np.uint8) * 255)[cy0:cy1, cx0:cx1]
    rgb_crop = rgb[cy0:cy1, cx0:cx1]
    rgba = np.dstack([rgb_crop, alpha])

    # Scale-invariant: normalize against the pre-scale crop, then resize.
    anchors: dict[str, list[float]] = {}
    for name in ANCHOR_LANDMARKS[garment_type]:
        px, py = landmarks_px[name]
        anchors[name] = [(px - cx0) / crop_w, (py - cy0) / crop_h]

    long_side = max(crop_w, crop_h)
    if long_side > IMAGE_LONG_SIDE_PX:
        scale = IMAGE_LONG_SIDE_PX / long_side
        new_w = max(1, round(crop_w * scale))
        new_h = max(1, round(crop_h * scale))
        rgba = np.asarray(Image.fromarray(rgba, mode="RGBA").resize((new_w, new_h), Image.LANCZOS))

    return rgba, anchors
