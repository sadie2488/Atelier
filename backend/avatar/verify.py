"""A-R10: verify generated output before swapping it in. Sample one representative patch per
garment (from the pre-crop pose landmarks used to build the rig) and compare it against the
item's stored primary_color in CIE Lab via CIEDE2000. Any garment over VERIFY_MAX_DELTA_E fails
verification -- the render stays `failed` and the local composite is what the user sees either
way (A-R6).

This is deliberately coarse: one small patch per garment, not per-pixel garment segmentation
(there is no segmenter in this lane's dependencies -- see mp_models.py). It exists to catch the
most common failure, Gemini swapping in the wrong color, not to grade texture or print fidelity,
which A-R7 already accepts as this method's weakness. Face-landmark drift is not checked here
(optional per A-R10); the identity-preservation instruction lives in prompt.py.
"""
from typing import Optional

import numpy as np

from contract.enums import GarmentType, SECONDARY_MIN_DELTA_E
from contract.tools.color import delta_e2000, hex_to_lab

# A-R10: how far the sampled generated-garment color may drift from the item's stored Lab color
# before the swap is rejected. Reused from the contract's own "clearly a different color"
# threshold (SECONDARY_MIN_DELTA_E) rather than inventing a new number: a lit, generated photo
# will drift more than a flat cutout scan, but past this point it reads as the wrong garment,
# not just different lighting.
VERIFY_MAX_DELTA_E = SECONDARY_MIN_DELTA_E  # 20.0

_PATCH = 14  # half-size of the sample square, px, in the generated image's own resolution


def _rgb_to_lab(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    r, g, b = (max(0, min(255, int(round(v)))) for v in rgb)
    return hex_to_lab(f"#{r:02x}{g:02x}{b:02x}")


def _patch_mean(img: np.ndarray, cx: float, cy: float) -> Optional[np.ndarray]:
    h, w = img.shape[:2]
    x0, x1 = max(0, int(cx) - _PATCH), min(w, int(cx) + _PATCH)
    y0, y1 = max(0, int(cy) - _PATCH), min(h, int(cy) + _PATCH)
    if x1 <= x0 or y1 <= y0:
        return None
    return img[y0:y1, x0:x1].reshape(-1, 3).astype(float).mean(axis=0)


def _mid(points: dict, a: str, b: str) -> tuple[float, float]:
    return ((points[a][0] + points[b][0]) / 2, (points[a][1] + points[b][1]) / 2)


def _region_point(garment_type: GarmentType, points: dict) -> Optional[tuple[float, float]]:
    """A point likely inside `garment_type`'s garment, in the source photo's own pixel space."""
    try:
        if garment_type in (GarmentType.shirt, GarmentType.dress):
            cx, cy = _mid(points, "left_shoulder", "right_shoulder")
            hx, hy = _mid(points, "left_hip", "right_hip")
            return (cx + hx) / 2, (cy + hy) / 2
        if garment_type in (GarmentType.jacket, GarmentType.coat):
            sh, el = points["left_shoulder"], points["left_elbow"]
            return (sh[0] + el[0]) / 2, (sh[1] + el[1]) / 2
        # pants, shorts, skirt: a point on the upper leg, closer to the hip than the knee
        hx, hy = _mid(points, "left_hip", "right_hip")
        kx, ky = _mid(points, "left_knee", "right_knee")
        return hx * 0.65 + kx * 0.35, hy * 0.65 + ky * 0.35
    except KeyError:
        return None


def verify_colors(
    generated_rgb: np.ndarray,
    source_landmarks: dict,
    source_size: tuple[int, int],
    garments: list[tuple[GarmentType, dict]],  # (garment_type, item's primary_color dict)
) -> tuple[bool, str]:
    """-> (ok, reason). `source_landmarks`: {name: [x, y]} in the ORIGINAL scan photo's pixel
    space (the same photo sent to Gemini). Rescaled to the generated image's own resolution in
    case the model returned a different size.
    """
    gh, gw = generated_rgb.shape[:2]
    sw, sh = source_size
    scale_x = (gw / sw) if sw else 1.0
    scale_y = (gh / sh) if sh else 1.0

    for garment_type, primary_color in garments:
        point = _region_point(garment_type, source_landmarks)
        if point is None:
            continue  # can't locate this garment's region; don't fail the render over it
        sample = _patch_mean(generated_rgb, point[0] * scale_x, point[1] * scale_y)
        if sample is None:
            continue
        sampled_lab = _rgb_to_lab(tuple(sample))
        stored_lab = tuple(primary_color["lab"])
        de = delta_e2000(stored_lab, sampled_lab)
        if de > VERIFY_MAX_DELTA_E:
            return False, f"{garment_type.value} color drifted (dE2000={de:.1f} > {VERIFY_MAX_DELTA_E})"

    return True, "ok"
