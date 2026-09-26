"""A-B5: skin tone sampled from exposed regions (forearms, shins), falling back to the face
region when the user is scanned in long sleeves and pants. The face is always available (A-B8).
"""
from typing import Optional

import numpy as np

_PATCH = 6  # half-size of the sample square, px


def _patch_mean(rgb: np.ndarray, cx: float, cy: float) -> Optional[tuple[float, float, float]]:
    h, w = rgb.shape[:2]
    x0, x1 = max(0, int(cx) - _PATCH), min(w, int(cx) + _PATCH)
    y0, y1 = max(0, int(cy) - _PATCH), min(h, int(cy) + _PATCH)
    if x1 <= x0 or y1 <= y0:
        return None
    patch = rgb[y0:y1, x0:x1].reshape(-1, 3).astype(float)
    m = patch.mean(axis=0)
    return (float(m[0]), float(m[1]), float(m[2]))


def _looks_like_skin(rgb: tuple[float, float, float]) -> bool:
    r, g, b = rgb
    return r > 60 and r > g > b and (r - b) > 15 and (r - g) > 5


def sample_skin_tone(
    rgb: np.ndarray,
    landmarks_px: dict[str, tuple[float, float, float]],
    face_patch_center: Optional[tuple[float, float]] = None,
) -> tuple[int, int, int]:
    """-> (r, g, b) uint8. Tries forearms/shins first; falls back to the face region."""
    pts = {n: (x, y) for n, (x, y, _v) in landmarks_px.items()}

    candidates = []
    for side in ("left", "right"):
        if f"{side}_elbow" in pts and f"{side}_wrist" in pts:
            e, wr = pts[f"{side}_elbow"], pts[f"{side}_wrist"]
            candidates.append(((e[0] + wr[0]) / 2, (e[1] + wr[1]) / 2))
        if f"{side}_knee" in pts and f"{side}_ankle" in pts:
            k, a = pts[f"{side}_knee"], pts[f"{side}_ankle"]
            candidates.append(((k[0] + a[0]) / 2, (k[1] + a[1]) / 2))

    skin_samples = []
    for cx, cy in candidates:
        mean = _patch_mean(rgb, cx, cy)
        if mean is not None and _looks_like_skin(mean):
            skin_samples.append(mean)

    if skin_samples:
        arr = np.array(skin_samples).mean(axis=0)
        return int(arr[0]), int(arr[1]), int(arr[2])

    # A-B8 fallback: face-region tone.
    if face_patch_center is not None:
        mean = _patch_mean(rgb, *face_patch_center)
        if mean is not None:
            return int(mean[0]), int(mean[1]), int(mean[2])

    if "nose" in pts:
        mean = _patch_mean(rgb, pts["nose"][0], pts["nose"][1] + 20)
        if mean is not None:
            return int(mean[0]), int(mean[1]), int(mean[2])

    return (210, 180, 160)  # last-resort neutral tone; a scan never fails over skin sampling
