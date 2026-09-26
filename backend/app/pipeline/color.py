"""Cutout RGBA -> 1..MAX_COLORS colors {lab, lch, hex, weight} from opaque pixels, plus is_neutral."""
import math

import numpy as np
from skimage.color import deltaE_ciede2000, lab2rgb, rgb2lab
from sklearn.cluster import KMeans

from contract.enums import (
    COLOR_MERGE_DELTA_E,
    MAX_COLORS,
    MIN_COLOR_WEIGHT,
    NEUTRAL_CHROMA_MAX,
    ErrorCode,
)
from app.pipeline import PipelineError

SAMPLE_PIXELS = 20000


def lab_to_hex(lab) -> str:
    rgb = lab2rgb(np.array(lab, dtype=np.float64).reshape(1, 1, 3)).reshape(3)
    return "#" + "".join(f"{round(float(c) * 255):02x}" for c in np.clip(rgb, 0, 1))


def lab_to_lch(lab) -> tuple[float, float, float]:
    L, a, b = lab
    h = round(math.degrees(math.atan2(b, a)) % 360, 2)
    return (L, round(math.hypot(a, b), 2), 0.0 if h >= 360 else h)


def _merge(centers: list[np.ndarray], weights: list[float]):
    centers, weights = list(centers), list(weights)
    while len(centers) > 1:
        best = None
        for i in range(len(centers)):
            for j in range(i + 1, len(centers)):
                d = float(deltaE_ciede2000(centers[i], centers[j]))
                if best is None or d < best[0]:
                    best = (d, i, j)
        d, i, j = best
        if d >= COLOR_MERGE_DELTA_E:
            break
        w = weights[i] + weights[j]
        centers[i] = (centers[i] * weights[i] + centers[j] * weights[j]) / w
        weights[i] = w
        del centers[j], weights[j]
    return centers, weights


def extract_colors(rgba: np.ndarray, seed: int = 0) -> tuple[list[dict], bool]:
    opaque = rgba[..., 3] >= 128
    px = rgba[..., :3][opaque]
    if len(px) == 0:
        raise PipelineError(ErrorCode.mask_out_of_range, "Cutout has no opaque pixels.")
    rng = np.random.default_rng(seed)
    if len(px) > SAMPLE_PIXELS:
        px = px[rng.choice(len(px), SAMPLE_PIXELS, replace=False)]
    lab = rgb2lab(px.reshape(-1, 1, 3).astype(np.float64) / 255).reshape(-1, 3)

    k = min(MAX_COLORS, len(np.unique(px, axis=0)))
    km = KMeans(n_clusters=k, n_init=4, random_state=seed).fit(lab)
    counts = np.bincount(km.labels_, minlength=k)
    centers = [lab[km.labels_ == i].mean(axis=0) for i in range(k) if counts[i]]
    weights = [counts[i] / len(lab) for i in range(k) if counts[i]]

    centers, weights = _merge(centers, weights)
    kept = sorted(
        ((w, c) for w, c in zip(weights, centers) if w >= MIN_COLOR_WEIGHT),
        key=lambda t: t[0],
        reverse=True,
    )[:MAX_COLORS]

    colors = []
    for w, c in kept:
        L = round(float(np.clip(c[0], 0, 100)), 2)
        a = round(float(np.clip(c[1], -128, 128)), 2)
        b = round(float(np.clip(c[2], -128, 128)), 2)
        colors.append({"lab": (L, a, b), "lch": lab_to_lch((L, a, b)), "hex": lab_to_hex((L, a, b)),
                       "weight": round(float(w), 4)})
    is_neutral = colors[0]["lch"][1] < NEUTRAL_CHROMA_MAX
    return colors, is_neutral
