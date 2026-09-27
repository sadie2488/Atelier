"""V3 edge quality (bottoms re-dispatch, human request): "the bottoms look better. Try and keep
edges straight, as they tend to be straight or slightly curved (like the bottom of shorts)."

Today's segmenter/mask noise leaves the waistband and hem (leg-opening) boundaries of pants/
shorts/skirt ragged -- small jagged in/out steps from mask noise, fraying, or the segmenter's own
blockiness -- even once the garment is otherwise correctly isolated (segmentation.py's V6/V6.2/V2
isolation work). This module regularizes ONLY those two boundaries (plus light smoothing on the
side seams), applied to each candidate's final mask, right after `_morph` and before
`artifact.build_cutout` crops/anchors it:

  1. Side seams: a light morphological open+close (radius `EDGE_SIDE_SMOOTH_PX`) denoises jagged
     contour steps without straightening -- a flared/baggy leg's silhouette is a real shape, not
     noise, so it is never line-fit.
  2. Waistband (top boundary) and each hem (bottom boundary of each leg -- two for pants/shorts,
     one continuous hem for a skirt): a robust (outlier-rejecting) fit of the boundary's (x, y)
     points, straight by default, escalating to a *gently* curved quadratic only when a straight
     line clearly doesn't track the boundary -- matching the human's "straight or slightly curved"
     framing (a shorts hem legitimately curves a little; a jean hem or waistband does not).
     Pixels beyond `EDGE_TOLERANCE_PX` of the fitted curve are trimmed (spikes) or filled (gaps)
     -- the tolerance band is deliberately generous enough to leave a modestly frayed/distressed
     hem still slightly irregular rather than perfectly ruled (per the human's ask), while still
     killing the big spikes/notches that read as "ragged." A boundary fit that still misses badly
     even after outlier rejection (see `_fit_edge_curve`'s `EDGE_GIVE_UP_RMSE_PX` gate) is left
     alone rather than forced -- a real waistband/hem is one coherent curve, so a fit this bad
     usually means a pre-existing segmentation defect, which is this module's cue to do nothing
     rather than make it worse.
  3. Hard safety net: whatever the above two steps do, the result is clipped to
     (a small dilation of the ORIGINAL mask) ∩ (clothes category) -- it can never grow onto skin
     or background by more than `EDGE_SAFETY_GROW_PX`, and never outside what the segmenter itself
     called "clothes" to begin with (V-S1: skin exclusion stays MediaPipe-category-only, never
     color).

Tuned by eye against the 9 real bottoms in the closet DB (pants: bottom_6b839f, bottom_e7883c,
bottom_62acf6, bottom_6a01d4; shorts: bottom_f91783, bottom_418fa7, bottom_36a1e0, bottom_d7459a,
bottom_dd2bea -- no skirt currently in the DB) via
backend/vision/scripts/reprocess_item.py, 2026-09-27. See candidate_params.py for the tunables.
"""
import numpy as np
from scipy import ndimage

from contract.enums import GarmentType

from .candidate_params import (
    EDGE_CONNECTIVITY_DROP_TOL, EDGE_FIT_MAX_ITER, EDGE_GIVE_UP_RMSE_PX, EDGE_LEG_SPLIT_MIN_AREA_FRAC,
    EDGE_LEG_SPLIT_MIN_Y_FRAC, EDGE_LINE_RMSE_OK_PX, EDGE_MAX_CURVATURE_PX, EDGE_MIN_FIT_POINTS,
    EDGE_OUTLIER_FLOOR_PX, EDGE_SAFETY_GROW_PX, EDGE_SIDE_SMOOTH_PX, EDGE_TOLERANCE_PX,
)
from .segmentation import _fill_small_holes

_BOTTOM_TYPES = (GarmentType.pants, GarmentType.shorts, GarmentType.skirt)


def _largest_cc_fraction(mask: np.ndarray) -> float:
    total = int(mask.sum())
    if total == 0:
        return 0.0
    labeled, n = ndimage.label(mask)
    if n == 0:
        return 0.0
    counts = np.bincount(labeled.ravel())
    counts[0] = 0
    return float(counts.max()) / total


def _robust_fit(xs: np.ndarray, ys: np.ndarray, degree: int) -> np.ndarray:
    """Least-squares polynomial fit with iterative outlier rejection (a lightweight RANSAC/IRLS
    hybrid): fit, drop points whose residual exceeds ~3.5x the (robust) median absolute deviation
    of the current residuals, refit on the survivors, repeat. Never drops below half the points
    or `degree + 2`, whichever is larger, so a genuinely noisy edge still gets a real fit instead
    of degenerating onto a lucky handful of points."""
    coeffs = np.polyfit(xs, ys, degree)
    keep = np.ones(len(xs), dtype=bool)
    min_points = max(degree + 2, len(xs) // 2)
    for _ in range(EDGE_FIT_MAX_ITER):
        idx = np.where(keep)[0]
        fit = np.polyval(coeffs, xs[idx])
        resid = ys[idx] - fit
        mad = float(np.median(np.abs(resid - np.median(resid))))
        thresh = max(EDGE_OUTLIER_FLOOR_PX, 3.5 * mad)
        local_keep = np.abs(resid) <= thresh
        if local_keep.all():
            break
        candidate = keep.copy()
        candidate[idx] = local_keep
        if candidate.sum() < min_points:
            break
        keep = candidate
        coeffs = np.polyfit(xs[keep], ys[keep], degree)
    return coeffs


def _fit_edge_curve(xs: np.ndarray, ys: np.ndarray) -> np.ndarray | None:
    """Straight by default; escalates to a gently-curved quadratic only when a robust line
    clearly doesn't track the boundary (`EDGE_LINE_RMSE_OK_PX`), and caps the quadratic's own sag
    (its max deviation from the straight line implied by its endpoints, over the observed span)
    at `EDGE_MAX_CURVATURE_PX` -- a "gentle curve" (a shorts hem) is allowed; a wild parabola
    fit to a couple of noisy points is not.

    Returns None (give up on this boundary; caller leaves it unregularized) when even the
    quadratic still misses the boundary by more than `EDGE_GIVE_UP_RMSE_PX` measured against
    EVERY point (not just the fit's own inliers) -- a real waistband/hem is one coherent curve,
    so a fit this bad means the boundary itself isn't one (e.g. a pre-existing segmentation defect
    -- a stray "clothes" blob elsewhere in frame connected by a thin bridge -- gives a boundary
    that jumps most of the canvas height across a handful of columns). Confirmed against "dark
    indigo wash Super High-Waisted Baggy Wide-Leg Jean #e2e7ea.webp" (bottom_e7883c): its mask had
    a bridge like this, and forcing a fit through it deleted ~65% of the correctly-segmented
    garment. This gate is an edge-quality feature's job to decline gracefully on, not to repair --
    that repair belongs in segmentation.py's own isolation logic."""
    line_coeffs = _robust_fit(xs, ys, 1)
    line_rmse = float(np.sqrt(np.mean((ys - np.polyval(line_coeffs, xs)) ** 2)))
    if line_rmse <= EDGE_LINE_RMSE_OK_PX:
        return np.array([0.0, line_coeffs[0], line_coeffs[1]])
    quad_coeffs = _robust_fit(xs, ys, 2)
    span = float(xs.max() - xs.min()) if len(xs) else 0.0
    sag = abs(quad_coeffs[0]) * (span ** 2) / 4.0
    if sag > EDGE_MAX_CURVATURE_PX and sag > 0:
        quad_coeffs = quad_coeffs.copy()
        quad_coeffs[0] *= EDGE_MAX_CURVATURE_PX / sag
    full_rmse = float(np.sqrt(np.mean((ys - np.polyval(quad_coeffs, xs)) ** 2)))
    if full_rmse > EDGE_GIVE_UP_RMSE_PX:
        return None
    return quad_coeffs


def _boundary_xy(mask: np.ndarray, x0: int, x1: int, side: str) -> tuple[np.ndarray, np.ndarray] | None:
    """For each column in [x0, x1) that has any mask pixel, the column's topmost (`side="top"`)
    or bottommost (`side="bottom"`) True row. None if too few columns have mask pixels to fit."""
    cols = mask[:, x0:x1]
    any_col = cols.any(axis=0)
    if int(any_col.sum()) < EDGE_MIN_FIT_POINTS:
        return None
    xs = np.arange(x0, x1)[any_col]
    sub = cols[:, any_col]
    if side == "top":
        ys = sub.argmax(axis=0).astype(np.float64)
    else:
        ys = (sub.shape[0] - 1 - sub[::-1, :].argmax(axis=0)).astype(np.float64)
    return xs, ys


def _apply_edge_fit(
    working: np.ndarray, allowed: np.ndarray, xs: np.ndarray, coeffs: np.ndarray, side: str,
) -> np.ndarray:
    """Trims mask pixels more than `EDGE_TOLERANCE_PX` past the fitted curve (spikes) and fills
    gaps within that same tolerance band that `allowed` (the safety-clipped region) says are
    legitimately garment (small holes/notches from mask noise) -- see this module's docstring for
    why the tolerance band is generous enough to leave a modestly frayed hem still slightly
    irregular rather than perfectly ruled."""
    out = working.copy()
    h = working.shape[0]
    fitted = np.polyval(coeffs, xs)
    for i, x in enumerate(xs):
        y = fitted[i]
        if side == "top":
            cut = int(np.floor(y - EDGE_TOLERANCE_PX))
            fill_end = int(np.ceil(y + EDGE_TOLERANCE_PX)) + 1
            if cut > 0:
                out[:cut, x] = False
            y0, y1 = max(0, cut), min(h, fill_end)
        else:
            cut = int(np.ceil(y + EDGE_TOLERANCE_PX))
            fill_start = int(np.floor(y - EDGE_TOLERANCE_PX))
            if cut < h:
                out[cut:, x] = False
            y0, y1 = max(0, fill_start), min(h, cut + 1)
        if y1 > y0:
            out[y0:y1, x] |= allowed[y0:y1, x]
    return out


def _split_leg_masks(mask: np.ndarray) -> list[np.ndarray]:
    """Two legs (pants/shorts) as two separate masks over their own column range, so each hem is
    fit independently -- a single fit across both legs would cut straight through the gap between
    them. Purely mask-based (no pose landmarks): segmentation.py already documents cases where
    BlazePose's hip/knee/ankle are hallucinated or out-of-frame on a tight bottoms crop (its V2
    docstring), and this module has no way to tell a trusted landmark from an untrusted one --
    using hip/knee landmarks to decide the split risked cutting through the middle of one leg
    instead of the real crotch gap.

    Scans down from `EDGE_LEG_SPLIT_MIN_Y_FRAC` of the mask's own height (a real crotch is well
    below the waistband, never at the very top) for the first row where the mask already reads as
    exactly two components below it, EACH at least `EDGE_LEG_SPLIT_MIN_AREA_FRAC` of the mask's
    total area. That size floor is the key guard: a small stray fragment disconnected from the
    main mask near the top (a hanger clip or a strap still caught in the segmenter's "clothes"
    category, misclassified as its own tiny "leg") would otherwise be accepted as a valid split at
    row 0 and wrongly fit a hem to it -- confirmed against "livin it up Stretch Curvy Low-Rise
    Perfect Shortie #99b3be.png" (bottom_dd2bea): an unguarded split at row 0 picked out a 758px
    fragment (a hanger clip above the waistband, 1.4% of the mask) as "leg 1" and fit a hem to its
    own bottom boundary, deleting ~12% of the correctly-segmented shorts on the right side when
    that bogus hem was applied. Falls back to treating the whole mask as one hem if no row ever
    satisfies both guards (a wide/baggy leg still touching, or no valid crotch found at all) --
    safer than guessing a wrong split point."""
    ys = np.where(mask.any(axis=1))[0]
    if ys.size == 0:
        return [mask]
    y0, y1 = int(ys.min()), int(ys.max())
    height = y1 - y0
    if height <= 0:
        return [mask]
    total = int(mask.sum())
    min_area = EDGE_LEG_SPLIT_MIN_AREA_FRAC * total
    start = y0 + int(EDGE_LEG_SPLIT_MIN_Y_FRAC * height)

    for y in range(start, y1 + 1):
        row = mask[y]
        if not row.any():
            continue
        edges = np.diff(row.astype(np.int8))
        runs = int(np.sum(edges == 1)) + (1 if row[0] else 0)
        if runs < 2:
            continue
        lower = mask.copy()
        lower[:y, :] = False
        labeled, n = ndimage.label(lower)
        if n < 2:
            continue
        counts = np.bincount(labeled.ravel())
        counts[0] = 0
        top2 = [c for c in np.argsort(counts)[::-1][:2] if counts[c] > 0]
        if len(top2) == 2 and counts[top2[0]] >= min_area and counts[top2[1]] >= min_area:
            comps = [mask & (labeled == c) for c in top2]
            comps.sort(key=lambda m: float(np.where(m)[1].mean()))
            return comps
    return [mask]


def regularize_bottom_edges(
    mask: np.ndarray, garment_type: GarmentType, clothes: np.ndarray,
) -> np.ndarray:
    """-> `mask` unchanged for any garment_type other than pants/shorts/skirt, or if `mask` is
    empty. Otherwise: side-seam smoothing, then waistband + hem regularization (see module
    docstring), then a hard clip to `dilate(original mask, EDGE_SAFETY_GROW_PX) & clothes` so the
    result can never grow onto skin/background beyond a few pixels past what was there before."""
    if garment_type not in _BOTTOM_TYPES or not mask.any():
        return mask

    original = mask
    allowed = ndimage.binary_dilation(original, iterations=EDGE_SAFETY_GROW_PX) & clothes

    # Side seams: light contour smoothing only -- never straightened, never grown/shrunk beyond
    # a radius of EDGE_SIDE_SMOOTH_PX (opening can only erode-then-restore, closing can only
    # bridge a gap of that radius), so a flared/baggy leg's real shape survives. Guarded: opening
    # can sever a thin (segmenter-blocky) isthmus -- e.g. a high-waisted jean's narrow waist-to-
    # leg bridge -- that was otherwise part of one connected garment, which would fail V-Q3's
    # `structural_largest_cc_ratio` check outright. If smoothing would meaningfully drop the
    # largest-connected-component fraction, skip it and regularize the un-smoothed mask instead.
    if EDGE_SIDE_SMOOTH_PX > 0:
        smoothed = ndimage.binary_opening(mask, iterations=EDGE_SIDE_SMOOTH_PX)
        smoothed = ndimage.binary_closing(smoothed, iterations=EDGE_SIDE_SMOOTH_PX)
        if smoothed.any() and _largest_cc_fraction(smoothed) >= _largest_cc_fraction(mask) - EDGE_CONNECTIVITY_DROP_TOL:
            working = smoothed
        else:
            working = mask
    else:
        working = mask

    xs_present = np.where(working.any(axis=0))[0]
    if xs_present.size == 0:
        return mask
    x0, x1 = int(xs_present.min()), int(xs_present.max()) + 1

    # Waistband: one continuous top-boundary curve across the garment's full width.
    top_xy = _boundary_xy(working, x0, x1, "top")
    if top_xy is not None:
        xs, ys = top_xy
        coeffs = _fit_edge_curve(xs, ys)
        if coeffs is not None:
            working = _apply_edge_fit(working, allowed, xs, coeffs, "top")

    # Hems: skirts get one continuous bottom-boundary curve; pants/shorts get two independent
    # ones, one per leg (a single fit across both legs would cut straight through the gap between
    # them at the crotch).
    leg_masks = [working] if garment_type == GarmentType.skirt else _split_leg_masks(working)
    for leg in leg_masks:
        leg_xs_present = np.where(leg.any(axis=0))[0]
        if leg_xs_present.size == 0:
            continue
        lx0, lx1 = int(leg_xs_present.min()), int(leg_xs_present.max()) + 1
        bottom_xy = _boundary_xy(leg, lx0, lx1, "bottom")
        if bottom_xy is None:
            continue
        xs, ys = bottom_xy
        coeffs = _fit_edge_curve(xs, ys)
        if coeffs is not None:
            working = _apply_edge_fit(working, allowed, xs, coeffs, "bottom")

    working = working & allowed
    working = _fill_small_holes(working)
    return working if working.any() else mask
