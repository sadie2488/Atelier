"""V4 color: k-means k=5 in CIELAB over alpha>0 pixels -> primary + optional secondary.

V-C2: primary is the largest cluster by pixel mass. V-C3: secondary is emitted when a later
cluster holds >=20% of masked pixels and is >=dE2000 20 from the primary (largest by mass if
several qualify). V-C4/V-C5: name/family/is_neutral/everyday_neutral via contract/colors.json,
chroma-only for is_neutral.

V6: sampling erodes the alpha mask by COLOR_SAMPLE_EROSION_PX first (falling back to the
un-eroded mask if that would empty it). Diagnosed against fixtures/images: the cutout's edge is
antialiased against whatever sits behind it (background, hair, skin), so a ring of blended-color
pixels sits right at the boundary; on a small or thin cutout that ring is enough to seed its own
k-means cluster. Eroding a couple of pixels before sampling drops that ring without touching the
alpha channel actually shipped in the candidate (still "alpha > 0" per V-C2, just a stricter
interior subset of it).
"""
import numpy as np
from scipy import ndimage
from skimage.color import lab2rgb, rgb2lab
from sklearn.cluster import KMeans

from contract.enums import (
    COLOR_KMEANS_K, ErrorCode, NEUTRAL_CHROMA_MAX, SECONDARY_MIN_DELTA_E, SECONDARY_MIN_MASS,
)
from contract.tools.color import delta_e2000, display_name, lab_to_lch, nearest_color

from . import VisionError
from .candidate_params import COLOR_SAMPLE_EROSION_PX

_SAMPLE_PIXELS = 20000


def _lab_to_hex(lab: tuple[float, float, float]) -> str:
    rgb = lab2rgb(np.array(lab, dtype=np.float64).reshape(1, 1, 3)).reshape(3)
    rgb = np.clip(rgb, 0, 1)
    return "#" + "".join(f"{round(float(c) * 255):02x}" for c in rgb)


def _make_color(lab_raw) -> dict:
    L = round(float(np.clip(lab_raw[0], 0, 100)), 2)
    a = round(float(np.clip(lab_raw[1], -128, 128)), 2)
    b = round(float(np.clip(lab_raw[2], -128, 128)), 2)
    lab = (L, a, b)
    L2, C, h = lab_to_lch(lab)
    h = round(h, 2)
    if h >= 360:
        h -= 360
    lch = (round(L2, 2), round(C, 2), h)
    name, family, everyday_neutral = nearest_color(lab)
    return {
        "lab": lab,
        "lch": lch,
        "hex": _lab_to_hex(lab),
        "name": name,
        "family": family,
        "is_neutral": lch[1] < NEUTRAL_CHROMA_MAX,
        "everyday_neutral": everyday_neutral,
        # Contract 2.1.0: human-friendly display_name, nearest xkcd color-survey name by
        # CIEDE2000 -- UI-facing only. `name`/`family` (colors.json, used by styling) unchanged.
        "display_name": display_name(lab),
    }


def extract_colors(rgba: np.ndarray, seed: int = 0) -> tuple[dict, dict | None]:
    """RGBA cutout -> (primary ExtractedColor dict, secondary dict or None)."""
    alpha = rgba[..., 3] > 0
    if COLOR_SAMPLE_EROSION_PX > 0:
        eroded = ndimage.binary_erosion(alpha, iterations=COLOR_SAMPLE_EROSION_PX)
        if eroded.any():
            alpha = eroded
    px = rgba[..., :3][alpha]
    if px.size == 0:
        raise VisionError(ErrorCode.analyze_failed, "Cutout has no opaque pixels to extract color from.")

    rng = np.random.default_rng(seed)
    if len(px) > _SAMPLE_PIXELS:
        px = px[rng.choice(len(px), _SAMPLE_PIXELS, replace=False)]

    lab_px = rgb2lab(px.reshape(-1, 1, 3).astype(np.float64) / 255.0).reshape(-1, 3)

    k = min(COLOR_KMEANS_K, len(np.unique(px, axis=0)))
    k = max(k, 1)
    if k == 1:
        centers, counts = lab_px.mean(axis=0, keepdims=True), np.array([len(lab_px)])
    else:
        km = KMeans(n_clusters=k, n_init=4, random_state=seed).fit(lab_px)
        centers = km.cluster_centers_
        counts = np.bincount(km.labels_, minlength=k)

    order = np.argsort(-counts)
    total = counts.sum()
    clusters = [(centers[i], counts[i] / total) for i in order]

    primary_lab, _ = clusters[0]
    primary = _make_color(primary_lab)

    secondary = None
    qualifying = [
        (lab, mass) for lab, mass in clusters[1:]
        if mass >= SECONDARY_MIN_MASS and delta_e2000(tuple(lab), tuple(primary_lab)) >= SECONDARY_MIN_DELTA_E
    ]
    if qualifying:
        qualifying.sort(key=lambda t: -t[1])
        secondary = _make_color(qualifying[0][0])

    return primary, secondary
