"""A-B5: skin tone sampled from exposed skin regions, found with MediaPipe ImageSegmenter's
skin categories (body-skin, face-skin -- see mp_models.image_segmenter), falling back to the
face region when segmentation finds no skin (long sleeves and pants; the face is always
available, A-B8). The color is the median in Lab space, not the mean in RGB, so a handful of
shadow or highlight pixels can't drag a fair or deep skin tone toward a muddy average; those
dark/clipped pixels are excluded from the candidate set before the median is taken.
"""
from typing import Optional

import numpy as np
from skimage.color import lab2rgb, rgb2lab

from .mp_models import image_segmenter

_PATCH = 6  # half-size of the face-region fallback sample square, px

# selfie_multiclass_256x256 category indices (see mp_models.py): 2 body-skin, 3 face-skin.
_SKIN_CATEGORIES = (2, 3)

# A pixel this dark (shadow) or this bright (blown highlight) doesn't reflect the true skin
# tone; excluded before the Lab median is computed. Checked on the RGB channel range, which is
# cheap and doesn't require a Lab conversion just to filter.
_DARK_MAX = 25
_CLIPPED_MIN = 250


def _lab_median_rgb(pixels_rgb: np.ndarray) -> Optional[tuple[int, int, int]]:
    """pixels_rgb: (N, 3) RGB in [0, 255]. -> the median-in-Lab color as (r, g, b), or None if
    nothing survives the dark/clipped filter."""
    if pixels_rgb.size == 0:
        return None
    pixels_rgb = pixels_rgb.astype(np.float64)
    channel_max = pixels_rgb.max(axis=1)
    channel_min = pixels_rgb.min(axis=1)
    keep = (channel_max > _DARK_MAX) & (channel_min < _CLIPPED_MIN)
    pixels_rgb = pixels_rgb[keep]
    if pixels_rgb.shape[0] == 0:
        return None

    lab = rgb2lab(pixels_rgb.reshape(-1, 1, 3) / 255.0).reshape(-1, 3)
    median_lab = np.median(lab, axis=0)
    rgb = lab2rgb(median_lab.reshape(1, 1, 3)).reshape(3) * 255.0
    rgb = np.clip(rgb, 0, 255)
    return int(round(rgb[0])), int(round(rgb[1])), int(round(rgb[2]))


def _segment_skin_pixels(rgb: np.ndarray) -> Optional[np.ndarray]:
    """-> (N, 3) RGB pixels the segmenter classified as body-skin or face-skin, or None if the
    model finds none (or segmentation itself fails -- A-B8, never blocks the scan)."""
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
    mask = np.isin(category_mask, _SKIN_CATEGORIES)
    if not mask.any():
        return None
    return rgb[mask]


def _patch_pixels(rgb: np.ndarray, cx: float, cy: float) -> Optional[np.ndarray]:
    h, w = rgb.shape[:2]
    x0, x1 = max(0, int(cx) - _PATCH), min(w, int(cx) + _PATCH)
    y0, y1 = max(0, int(cy) - _PATCH), min(h, int(cy) + _PATCH)
    if x1 <= x0 or y1 <= y0:
        return None
    return rgb[y0:y1, x0:x1].reshape(-1, 3)


def sample_skin_tone(
    rgb: np.ndarray,
    landmarks_px: dict[str, tuple[float, float, float]],
    face_patch_center: Optional[tuple[float, float]] = None,
) -> tuple[int, int, int]:
    """-> (r, g, b) uint8. A-B5: exposed skin regions via the segmenter's skin categories first;
    falls back to the face region, then a nose-adjacent patch, then a neutral tone (A-B8's
    "skin sampling fails -> face-region tone" plus one further last-resort rung)."""
    skin_pixels = _segment_skin_pixels(rgb)
    if skin_pixels is not None:
        color = _lab_median_rgb(skin_pixels)
        if color is not None:
            return color

    if face_patch_center is not None:
        patch = _patch_pixels(rgb, *face_patch_center)
        if patch is not None:
            color = _lab_median_rgb(patch)
            if color is not None:
                return color

    pts = {n: (x, y) for n, (x, y, _v) in landmarks_px.items()}
    if "nose" in pts:
        patch = _patch_pixels(rgb, pts["nose"][0], pts["nose"][1] + 20)
        if patch is not None:
            color = _lab_median_rgb(patch)
            if color is not None:
                return color

    return (210, 180, 160)  # last-resort neutral tone; a scan never fails over skin sampling
