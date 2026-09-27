"""Flat-lay (garment alone, no person) analyze path -- used by scripts/batch_ingest.py --flatlay
only; the live /api/items/analyze route is unchanged.

Segmentation: if the source image carries a real alpha channel (a pre-cut product PNG), the
alpha IS the garment mask. Otherwise the background is estimated from the border (k-means of a
border band, so a painted checkerboard's two colors plus smudges are all covered), background-like
pixels connected to the border are flood-filled away, the largest remaining component is
hole-filled (never shrunk by GrabCut), and soft floor shadow outside the garment hull is trimmed.

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


def _to_lab(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)   # true L 0-100


def _bg_model(lab: np.ndarray) -> tuple[np.ndarray, float]:
    """Border band -> (background centers Kx3, noise). One center (median) for a plain studio
    background; two for a painted checkerboard (both dominant border colors)."""
    h, w = lab.shape[:2]
    b = max(4, int(0.03 * min(h, w)))
    band = np.concatenate([lab[:b].reshape(-1, 3), lab[-b:].reshape(-1, 3),
                           lab[:, :b].reshape(-1, 3), lab[:, -b:].reshape(-1, 3)])
    med = np.median(band, axis=0)
    centers = med[None]
    d1 = np.linalg.norm(band - med, axis=1)
    if np.percentile(d1, 75) > 6.0:   # two-tone border (fake checkerboard)
        crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.5)
        _, lbl, c2 = cv2.kmeans(band.astype(np.float32), 2, None, crit, 2, cv2.KMEANS_PP_CENTERS)
        frac = np.bincount(lbl.ravel(), minlength=2) / len(lbl)
        centers = c2[frac >= 0.15]
        d2 = np.min(np.stack([np.linalg.norm(band - c, axis=1) for c in centers]), axis=0)
        if np.percentile(d2, 75) > 6.0:   # textured multi-tone background (wood floor, fabric, sunlight)
            _, lbl, c8 = cv2.kmeans(band.astype(np.float32), 8, None, crit, 3, cv2.KMEANS_PP_CENTERS)
            frac = np.bincount(lbl.ravel(), minlength=8) / len(lbl)
            centers = c8[frac >= 0.02]
            d = np.min(np.stack([np.linalg.norm(band - c, axis=1) for c in centers]), axis=0)
            return centers, float(max(np.percentile(d, 90), 6.0))
    d = np.min(np.stack([np.linalg.norm(band - c, axis=1) for c in centers]), axis=0)
    return centers, float(np.percentile(d, 90))


def _border_bg(lab: np.ndarray, centers: np.ndarray, tol: float) -> np.ndarray:
    """Pixels within tol of a background color AND 4-connected to the image border."""
    d = np.min(np.stack([np.linalg.norm(lab - c, axis=2) for c in centers]), axis=0)
    bglike = d < tol
    bglike = bglike.astype(np.uint8)
    # flood only through thick background (thin paths of bg-colored garment pixels, e.g. a
    # white shirt's shading on grey, must not let the flood leak in), then regrow the edge
    thick = cv2.morphologyEx(bglike, cv2.MORPH_OPEN, _k(3))
    _, cc = cv2.connectedComponents(thick, connectivity=4)
    edge_ids = set(np.unique(np.concatenate([cc[0], cc[-1], cc[:, 0], cc[:, -1]]))) - {0}
    core = np.isin(cc, list(edge_ids)).astype(np.uint8)
    return (cv2.dilate(core, _k(4)) > 0) & (bglike > 0)


def _clean(fg: np.ndarray) -> np.ndarray:
    fg = cv2.morphologyEx(fg.astype(np.uint8), cv2.MORPH_CLOSE, _k(2)) > 0
    fg = cv2.morphologyEx(fg.astype(np.uint8), cv2.MORPH_OPEN, _k(1)) > 0
    return _fill_holes(_largest_cc(fg, 0.05))


def _shadow_trim(lab: np.ndarray, fg: np.ndarray, centers: np.ndarray, tol: float) -> np.ndarray:
    """Drop soft floor shadow: only slightly darker than the background, near-neutral, and
    not adjacent to the garment core. Enclosed regions are restored by hole filling."""
    bgc = centers[np.argmax(centers[:, 0])]
    dl = bgc[0] - lab[..., 0]
    dab = np.linalg.norm(lab[..., 1:] - bgc[1:], axis=2)
    shadow = fg & (dl > 0) & (dl < 22.0) & (dab < max(4.0, tol))
    core = _largest_cc(cv2.morphologyEx((fg & ~shadow).astype(np.uint8), cv2.MORPH_OPEN, _k(2)) > 0, 0.05)
    if core.sum() < 0.3 * fg.sum():
        return fg   # garment itself is shadow-colored (grey on grey): don't trim
    near = cv2.dilate(core.astype(np.uint8), _k(3)) > 0
    return _fill_holes(fg & ~(shadow & ~near))   # enclosed shadow-colored parts come back


def _border_segment(rgb: np.ndarray, gain: float) -> np.ndarray:
    """Background = near a border color (tolerance adaptive to the border's own noise) and
    connected to the border; garment = largest remaining component with ALL holes filled."""
    h, w = rgb.shape[:2]
    lab = _to_lab(rgb)
    centers, noise = _bg_model(lab)
    tol = max(1.5, gain * max(noise, 0.8))
    bg = _border_bg(lab, centers, tol)
    fg = _clean(~bg)
    if fg.sum() < 0.01 * h * w or fg.sum() > 0.97 * h * w:
        raise VisionError(ErrorCode.analyze_failed, "No garment found on the flat-lay background.")
    fg = _clean(_shadow_trim(lab, fg, centers, tol))
    if len(centers) > 2:   # textured background: drop thin attachments (hanger, strings) off the garment
        r = max(3, int(0.012 * min(h, w)))
        fg = _fill_holes(_largest_cc(cv2.morphologyEx(fg.astype(np.uint8), cv2.MORPH_OPEN, _k(r)) > 0, 0.05))
    return fg


def _masks(rgb: np.ndarray, alpha: np.ndarray | None) -> list[np.ndarray]:
    """-> [tight, balanced, generous] bool masks."""
    if alpha is not None:
        base = _largest_cc(alpha >= 128, 0.02)
        tight = _largest_cc(cv2.erode((alpha >= 200).astype(np.uint8), _k(1)) > 0, 0.02)
        gen = _largest_cc(alpha >= 40, 0.02)
        return [tight & base, base, gen]
    bal, err = None, None
    for gain in (3.0, 2.0, 1.4):   # white-on-white needs a low tolerance
        try:
            bal = _border_segment(rgb, gain)
            break
        except VisionError as e:
            err = e
    if bal is None:
        raise err
    try:
        tight = _border_segment(rgb, gain * 1.6) & bal
    except VisionError:
        tight = cv2.erode(bal.astype(np.uint8), _k(1)) > 0
    try:
        gen = _border_segment(rgb, gain * 0.6) | bal
    except VisionError:
        gen = bal
    gen = _fill_holes(cv2.dilate(gen.astype(np.uint8), _k(1)) > 0)
    # On busy backgrounds the re-segmented variants can bite into the garment or pick up
    # attachments (hanger): keep them as gentle variations of the balanced cut instead.
    if tight.sum() < 0.995 * bal.sum():
        tight = cv2.erode(bal.astype(np.uint8), _k(1)) > 0
    if gen.sum() > 1.01 * bal.sum():
        gen = _fill_holes(cv2.dilate(bal.astype(np.uint8), _k(1)) > 0)
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
