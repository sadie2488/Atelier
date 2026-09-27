"""Flat-lay (garment alone, no person) analyze path -- used by scripts/batch_ingest.py --flatlay
only; the live /api/items/analyze route is unchanged.

Segmentation: if the source image carries a real alpha channel (a pre-cut product PNG), the
alpha IS the garment mask. Otherwise the background is estimated from the border (k-means of a
border band, so a painted checkerboard's two colors plus smudges are all covered), background-like
pixels connected to the border are flood-filled away, the largest remaining component is
hole-filled and refined with GrabCut.

Anchors: there is no model, so the contract's pose landmarks are synthesized from the garment
mask geometry (shoulders at the top corners of the body, hips near the hem / waistband corners,
knees and ankles down the legs) in source pixels; build_cutout normalizes them to the cutout.
Output: the same candidate dicts as ingest.build_candidates.
"""
import io

import cv2
import numpy as np
from PIL import Image, ImageOps

from contract.enums import CandidateVariant, ErrorCode, GarmentType, IMAGE_LONG_SIDE_PX

from . import VisionError
from .artifact import build_cutout
from .checks import run_checks
from .color import extract_colors

_VARIANTS = [CandidateVariant.tight, CandidateVariant.balanced, CandidateVariant.generous]


# ----------------------------------------------------------------------------- loading
def _load(data: bytes) -> tuple[np.ndarray, np.ndarray | None]:
    """-> (HxWx3 uint8 RGB, HxW uint8 alpha or None when the image has no meaningful alpha)."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:
        raise VisionError(ErrorCode.unsupported_image, f"Could not decode image: {e}") from e
    img = ImageOps.exif_transpose(img).convert("RGBA")
    w, h = img.size
    scale = IMAGE_LONG_SIDE_PX / max(w, h)
    if scale < 1.0:
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    arr = np.asarray(img)
    alpha = arr[..., 3]
    # composite on white for color / display
    a = alpha[..., None].astype(np.float32) / 255.0
    rgb = (arr[..., :3].astype(np.float32) * a + 255.0 * (1 - a)).round().astype(np.uint8)
    frac_clear = float((alpha < 128).mean())
    return rgb, (alpha if 0.05 < frac_clear < 0.97 else None)


# ----------------------------------------------------------------------------- mask helpers
def _largest_cc(mask: np.ndarray, keep_frac: float = 0.02) -> np.ndarray:
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    if n <= 1:
        return mask.astype(bool)
    areas = stats[1:, cv2.CC_STAT_AREA]
    big = areas.max()
    keep = [i + 1 for i, a in enumerate(areas) if a >= keep_frac * big]
    return np.isin(lab, keep)


def _fill_holes(mask: np.ndarray) -> np.ndarray:
    m = mask.astype(np.uint8)
    h, w = m.shape
    pad = np.zeros((h + 2, w + 2), np.uint8)
    pad[1:-1, 1:-1] = m
    ff = pad.copy()
    cv2.floodFill(ff, np.zeros((h + 4, w + 4), np.uint8), (0, 0), 1)
    holes = ff[1:-1, 1:-1] == 0
    return mask.astype(bool) | holes


def _k(r):
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))


def _border_segment(rgb: np.ndarray, tol: float) -> np.ndarray:
    h, w = rgb.shape[:2]
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    b = max(4, int(0.03 * min(h, w)))
    band = np.concatenate([lab[:b].reshape(-1, 3), lab[-b:].reshape(-1, 3),
                           lab[:, :b].reshape(-1, 3), lab[:, -b:].reshape(-1, 3)])
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, _, centers = cv2.kmeans(band, 4, None, crit, 2, cv2.KMEANS_PP_CENTERS)
    d = np.min(np.stack([np.linalg.norm(lab - c, axis=2) for c in centers]), axis=0)
    bglike = (d < tol).astype(np.uint8)
    n, cc = cv2.connectedComponents(bglike, connectivity=4)
    edge_ids = set(np.unique(np.concatenate([cc[0], cc[-1], cc[:, 0], cc[:, -1]]))) - {0}
    bg = np.isin(cc, list(edge_ids)) & (bglike > 0)
    fg = ~bg
    fg = cv2.morphologyEx(fg.astype(np.uint8), cv2.MORPH_OPEN, _k(2)) > 0
    fg = _fill_holes(_largest_cc(fg, 0.05))
    if fg.sum() < 0.01 * h * w:
        raise VisionError(ErrorCode.analyze_failed, "No garment found on the flat-lay background.")
    # GrabCut refinement
    gc = np.full((h, w), cv2.GC_PR_BGD, np.uint8)
    gc[fg] = cv2.GC_PR_FGD
    gc[cv2.erode(fg.astype(np.uint8), _k(6)) > 0] = cv2.GC_FGD
    gc[cv2.erode(bg.astype(np.uint8), _k(6)) > 0] = cv2.GC_BGD
    try:
        bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
        cv2.grabCut(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), gc, None, bgd, fgd, 3, cv2.GC_INIT_WITH_MASK)
        ref = (gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD)
        ref = _fill_holes(_largest_cc(ref, 0.05))
        if ref.sum() > 0.5 * fg.sum():
            fg = ref
    except cv2.error:
        pass
    return fg


def _masks(rgb: np.ndarray, alpha: np.ndarray | None) -> list[np.ndarray]:
    """-> [tight, balanced, generous] bool masks."""
    if alpha is not None:
        base = _largest_cc(alpha >= 128, 0.02)
        tight = _largest_cc(cv2.erode((alpha >= 200).astype(np.uint8), _k(1)) > 0, 0.02)
        gen = _largest_cc(alpha >= 40, 0.02)
        return [tight & base, base, gen]
    bal, err = None, None
    for tol in (8.0, 5.0, 3.0, 2.0):   # white-on-white needs a low tolerance
        try:
            bal = _border_segment(rgb, tol)
            break
        except VisionError as e:
            err = e
    if bal is None:
        raise err
    tight = cv2.erode(bal.astype(np.uint8), _k(2)) > 0
    gen = cv2.dilate(bal.astype(np.uint8), _k(2)) > 0
    return [tight, bal, gen]


# ----------------------------------------------------------------------------- anchors
def _row_extent(mask, y):
    y = int(np.clip(y, 0, mask.shape[0] - 1))
    xs = np.where(mask[y])[0]
    return (float(xs.min()), float(xs.max())) if xs.size else None


def _band_extent(mask, y0, y1):
    """median left/right extent over rows y0..y1."""
    ls, rs = [], []
    for y in range(int(y0), int(max(y0 + 1, y1))):
        e = _row_extent(mask, y)
        if e:
            ls.append(e[0]); rs.append(e[1])
    if not ls:
        return None
    return float(np.median(ls)), float(np.median(rs))


def _anchors(mask: np.ndarray, gt: GarmentType) -> dict[str, tuple[float, float]]:
    ys, xs = np.where(mask)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    bh, bw = y1 - y0 + 1, x1 - x0 + 1
    cx = (x0 + x1) / 2
    lm: dict[str, tuple[float, float]] = {}

    def pair(name, y, ext):
        # MediaPipe naming: the person's left is the image's right
        l, r = ext
        lm[f"left_{name}"] = (r, y)
        lm[f"right_{name}"] = (l, y)

    if gt in (GarmentType.pants, GarmentType.shorts, GarmentType.skirt):
        hy = y0 + 0.03 * bh
        he = _band_extent(mask, y0, y0 + 0.06 * bh) or (x0, x1)
        pair("hip", hy, he)
        hw = he[1] - he[0]
        leg = hw * 0.25  # leg centres at the quarter points of the waist
        if gt == GarmentType.pants:
            ky, ay = y0 + 0.55 * bh, y0 + 0.97 * bh
        else:  # shorts/skirt: garment ends above the knee; knee/ankle lie below the hem
            span = hw * 1.9  # approx hip->ankle length relative to waist width
            ky, ay = hy + span * 0.5, hy + span
        pair("knee", ky, (he[0] + leg, he[1] - leg))
        pair("ankle", ay, (he[0] + leg, he[1] - leg))
        return lm

    # tops / jackets / coats / dresses: body width from the torso band just under the collar
    se = _band_extent(mask, y0 + 0.04 * bh, y0 + 0.10 * bh) or (x0, x1)
    sw = se[1] - se[0]
    sy = y0 + 0.07 * bh
    # a sleeved garment's top band can already include sleeve; keep shoulders within the body
    body_w = min(sw, bw)
    sl, sr = cx - body_w / 2, cx + body_w / 2
    pair("shoulder", sy, (sl, sr))
    if gt == GarmentType.dress:
        hy = y0 + 0.38 * bh
        pair("hip", hy, (cx - body_w * 0.4, cx + body_w * 0.4))
        pair("ankle", y0 + 0.98 * bh, (cx - body_w * 0.2, cx + body_w * 0.2))
        return lm
    hy = y0 + 0.92 * bh if gt == GarmentType.shirt else y0 + min(0.92 * bh, sw * 1.3)
    if gt == GarmentType.coat:
        hy = sy + sw * 1.2
    he = _band_extent(mask, hy - 2, hy + 2) or (sl, sr)
    hl, hr = max(he[0], cx - body_w * 0.45), min(he[1], cx + body_w * 0.45)
    pair("hip", hy, (hl, hr))
    if gt in (GarmentType.jacket, GarmentType.coat):
        # wrists: lowest mask point in each outer quarter (sleeve cuffs)
        # (outer 12% only, so a long coat's hem is not mistaken for a cuff)
        for side, (a, b) in (("right", (x0, x0 + bw * 0.12)), ("left", (x1 - bw * 0.12, x1 + 1))):
            sub = mask[:, int(a):int(b)]
            yy, xx = np.where(sub)
            if yy.size:
                i = np.argmax(yy)
                lm[f"{side}_wrist"] = (float(xx[i] + int(a)), float(yy[i]))
            else:
                lm[f"{side}_wrist"] = (float(a), float(y1))
    return lm


# ----------------------------------------------------------------------------- entry points
def analyze_flatlay_bytes(data: bytes, category, garment_type) -> tuple[list[dict], bool, bool]:
    """Same return shape as ingest.build_candidates."""
    rgb, alpha = _load(data)
    return analyze_flatlay(rgb, category, garment_type, alpha=alpha), False, False


def analyze_flatlay(rgb: np.ndarray, category, garment_type, alpha: np.ndarray | None = None) -> list[dict]:
    gt = GarmentType(garment_type)
    masks = _masks(rgb, alpha)
    zeros = np.zeros(rgb.shape[:2], bool)
    out = []
    for variant, mask in zip(_VARIANTS, masks):
        if mask.sum() == 0:
            mask = masks[1]
        lm = _anchors(masks[1], gt)  # same anchors for all three
        rgba, anchors = build_cutout(rgb, mask, lm, gt)
        primary, secondary = extract_colors(rgba)
        checks = run_checks(mask, zeros, masks[2], rgba[..., 3] > 0, category)
        out.append({"variant": variant, "rgba": rgba, "anchors": anchors,
                    "primary_color": primary, "secondary_color": secondary, "checks": checks})
    return out
