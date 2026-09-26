"""Automated candidate quality checks (V-Q1..V-Q3). V-Q4 golden references don't exist yet
(no human pass has been run), so there is no IoU-against-reference gate here -- these checks
are informational: used to log full results at reject time (V-F3) and to report pass rates
against the fixture set. They do not block analyze/save.

Implemented:
  purity_skin_le_1pct              - V-Q1: skin <=1% of alpha area (MediaPipe categories only)
  purity_no_large_skin_blob        - V-Q1: no contiguous skin region >0.3% of alpha area
  purity_corners_transparent       - V-Q1: all four canvas corners alpha 0
  completeness_bbox_vs_extent      - V-Q2: mask bbox >=90% of the independent (V-S2) extent
  completeness_holes_le_2pct       - V-Q2: no interior holes >2% of alpha area
  completeness_no_straight_run     - V-Q2: no alpha boundary follows a straight line for more
                                     than 15% of canvas width (a sign the mask was truncated by
                                     an axis-aligned region/crop box rather than following the
                                     garment's own silhouette)
  completeness_left_right_balance  - V-Q2: for tops/bottoms only, left- and right-half alpha
                                     mass are within 25% of each other; jackets and other
                                     categories are legitimately asymmetric so this check passes
                                     them through unchecked
  structural_alpha_present         - V-Q3: alpha present and not fully opaque
  structural_coverage_in_range     - V-Q3: coverage ratio 8%-70%
  structural_largest_cc_ratio      - V-Q3: largest connected component / total alpha >= 0.90
"""
import numpy as np
from scipy import ndimage

from contract.enums import Category


def _largest_component_area(mask: np.ndarray) -> int:
    labeled, n = ndimage.label(mask)
    if n == 0:
        return 0
    counts = np.bincount(labeled.ravel())
    counts[0] = 0  # background label
    return int(counts.max())


def _max_flat_run(edge: np.ndarray) -> int:
    """`edge`: 1D array of boundary positions (one per row/column), -1 where the mask is absent
    there. Returns the longest run of consecutive present positions that don't move -- i.e. the
    longest flat (straight, axis-aligned) stretch of that boundary."""
    best = run = 0
    prev = None
    for v in edge:
        if v < 0:
            prev = None
            run = 0
            continue
        run = run + 1 if v == prev else 1
        best = max(best, run)
        prev = v
    return best


def _no_straight_boundary_run(mask: np.ndarray, max_frac: float = 0.15) -> bool:
    """V-Q2: flags a flat top/bottom edge (constant row per column -- a run measured in columns,
    a real horizontal length) or a flat left/right edge (constant column per row -- a run
    measured in rows) longer than `max_frac` of canvas width. Both run kinds are compared to the
    same width-based limit per DECISIONS.md's literal wording; in practice the runs this catches
    come from an axis-aligned pose-region or crop-box edge slicing across the mask, so either
    orientation is a real defect regardless of which pixel count it's measured in."""
    h, w = mask.shape
    if h == 0 or w == 0:
        return True
    limit = max_frac * w

    cols_any = mask.any(axis=0)
    top = np.where(cols_any, mask.argmax(axis=0), -1)
    bottom = np.where(cols_any, h - 1 - mask[::-1, :].argmax(axis=0), -1)

    rows_any = mask.any(axis=1)
    left = np.where(rows_any, mask.argmax(axis=1), -1)
    right = np.where(rows_any, w - 1 - mask[:, ::-1].argmax(axis=1), -1)

    runs = [_max_flat_run(top), _max_flat_run(bottom), _max_flat_run(left), _max_flat_run(right)]
    return max(runs) <= limit


def _left_right_balance_ok(cutout_alpha: np.ndarray, category, max_frac: float = 0.25) -> bool:
    """V-Q2: left/right alpha-mass balance, tops and bottoms only (a jacket may hang open or be
    shot at an angle and is legitimately asymmetric)."""
    if category not in (Category.tops, Category.bottoms):
        return True
    _, cw = cutout_alpha.shape
    mid = cw // 2
    left = int(cutout_alpha[:, :mid].sum())
    right = int(cutout_alpha[:, mid:].sum())
    total = left + right
    if total == 0:
        return False
    return abs(left - right) / total <= max_frac


def run_checks(mask: np.ndarray, skin_mask: np.ndarray, independent_extent_mask: np.ndarray,
               cutout_alpha: np.ndarray, category=None) -> dict:
    """`mask`, `skin_mask`, `independent_extent_mask`: HxW bool over the pre-crop working image
    (V-S1/V-S2 signals only make sense in that frame). `cutout_alpha`: HxW bool alpha of the
    final cropped-to-bbox canvas (V3), used for the corner and coverage-of-region checks.
    `category` (contract.enums.Category or None) gates the tops/bottoms-only left/right balance
    check (V-Q2); pass None to skip it.
    Returns a flat dict of check name -> bool (plus a raw pixel count for the reject log)."""
    total = int(mask.sum())
    ch, cw = cutout_alpha.shape

    if total == 0:
        return {
            "alpha_area_px": 0,
            "purity_skin_le_1pct": False,
            "purity_no_large_skin_blob": False,
            "purity_corners_transparent": False,
            "completeness_bbox_vs_extent": False,
            "completeness_holes_le_2pct": False,
            "completeness_no_straight_run": False,
            "completeness_left_right_balance": False,
            "structural_alpha_present": False,
            "structural_coverage_in_range": False,
            "structural_largest_cc_ratio": False,
        }

    skin_in_alpha = skin_mask & mask
    skin_pct = float(skin_in_alpha.sum()) / total
    largest_skin = _largest_component_area(skin_in_alpha)

    ys, xs = np.where(mask)
    bbox_area = (int(xs.max()) - int(xs.min()) + 1) * (int(ys.max()) - int(ys.min()) + 1)
    extent_area = int(independent_extent_mask.sum())

    filled = ndimage.binary_fill_holes(mask)
    holes = filled & ~mask
    holes_pct = float(holes.sum()) / total

    # Coverage relative to the plausible garment region (V-S2 extent), not the whole photo --
    # a tight bbox-crop of the final canvas would trivially read >90% and defeat the check.
    coverage = total / extent_area if extent_area else 0.0
    largest_cc = _largest_component_area(mask)

    corners_transparent = not (cutout_alpha[0, 0] or cutout_alpha[0, cw - 1]
                                or cutout_alpha[ch - 1, 0] or cutout_alpha[ch - 1, cw - 1])

    return {
        "alpha_area_px": total,
        "purity_skin_le_1pct": skin_pct <= 0.01,
        "purity_no_large_skin_blob": (largest_skin / total) <= 0.003,
        "purity_corners_transparent": bool(corners_transparent),
        "completeness_bbox_vs_extent": (bbox_area >= 0.90 * extent_area) if extent_area else False,
        "completeness_holes_le_2pct": holes_pct <= 0.02,
        "completeness_no_straight_run": _no_straight_boundary_run(cutout_alpha),
        "completeness_left_right_balance": _left_right_balance_ok(cutout_alpha, category),
        "structural_alpha_present": bool(cutout_alpha.any() and not cutout_alpha.all()),
        "structural_coverage_in_range": 0.08 <= coverage <= 0.70,
        "structural_largest_cc_ratio": (largest_cc / total) >= 0.90,
    }


def mask_iou(a: np.ndarray, b: np.ndarray) -> float:
    """V-E1: candidates must not collapse to near-identical masks (no two within 3% IoU)."""
    union = (a | b).sum()
    if union == 0:
        return 1.0
    return float((a & b).sum()) / float(union)
