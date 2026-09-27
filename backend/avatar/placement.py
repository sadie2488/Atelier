"""A4: garments placed via a similarity transform from cutout anchors to avatar rig landmarks
(contract/ARTIFACT_SPEC.md). Uniform scale + rotation + translation only -- garments are never
stretched non-uniformly. An item missing a required anchor falls back to its alpha bounding box
aligned to the avatar's landmark span for that region; logged, never fails the render.

FE-2 fix (2026-09-27, human-flagged): anchoring a bottom hip-to-hip put its waistband at the
AVATAR's hip *landmark* every time, regardless of the garment's own rise -- MediaPipe's hip
landmark sits low (near the hip joint), so this reads as "everything sits too low" even though
the transform is technically correct. Bottoms now get an extra vertical-only correction after the
hip-to-hip transform: `_bottom_rise_t` infers the garment's rise (high/mid/low) from how far above
the model's own hip landmarks its waistband (the cutout's own top edge) sits, relative to that
model's hip-to-knee span, and `place_item` shifts the placement (translation only -- scale and
rotation still come from the real hip-to-hip match) so the waistband lands at the avatar's own
natural-waist point for that rise instead of always at the raw hip line. Defaults to mid-rise
whenever the rise can't be determined (missing/degenerate anchors) -- never lower than that.
"""
import math
from typing import Optional

import numpy as np
from PIL import Image

from contract.enums import GarmentType

from .rig import Rig

# Primary anchor pair per ARTIFACT_SPEC: shoulders for tops/dress/jacket/coat, hips for bottoms.
PRIMARY_ANCHORS: dict[GarmentType, tuple[str, str]] = {
    GarmentType.shirt: ("left_shoulder", "right_shoulder"),
    GarmentType.jacket: ("left_shoulder", "right_shoulder"),
    GarmentType.coat: ("left_shoulder", "right_shoulder"),
    GarmentType.dress: ("left_shoulder", "right_shoulder"),
    GarmentType.pants: ("left_hip", "right_hip"),
    GarmentType.skirt: ("left_hip", "right_hip"),
    GarmentType.shorts: ("left_hip", "right_hip"),
}

BOTTOM_TYPES = (GarmentType.pants, GarmentType.skirt, GarmentType.shorts)

# Where the waistband should land on the avatar, as a fraction of the shoulder-mid -> hip-mid
# span (0 = shoulders, 1 = the hip line -- today's old, always-too-low default). HIGH_RISE_T
# lands near the torso's natural waist (matches draw.py's own waist point for the drawn torso
# silhouette, t=0.55 -- human judgment call, not a measured body-proportion constant).
HIGH_RISE_WAIST_T = 0.55
MID_RISE_WAIST_T = 0.78
LOW_RISE_WAIST_T = 1.00  # unchanged from before this fix: the hip line itself

# Rise classification thresholds: (hip_anchor_y - waistband_top_y) / (knee_anchor_y - hip_anchor_y)
# in the CUTOUT's own normalized coordinates -- i.e. how far above the model's hip the waistband
# sits, scaled by that same model's hip-to-knee span so it's comparable across garments/crops of
# different lengths. Human judgment calls, not measured constants; tune against real catalog items.
RISE_HIGH_RATIO = 0.22
RISE_LOW_RATIO = 0.06

# Scale/tilt fix (2026-09-27): the stored anchors ARE in the cutout's own normalized frame (vision
# `artifact.build_cutout` follows ARTIFACT_SPEC exactly; tops' shoulders/hips land where they
# should). But on bottoms the landmarks themselves are unusable: retail bottoms photos crop the
# model's head/torso off, and MediaPipe Pose then hallucinates hips/knees (measured on all 9
# catalog bottoms: hips below the cutout, off to one side, 3 px apart, or at 30 deg). A 2-point
# similarity fit to those points is what drew bottoms 2-10x oversized and tilted. So the primary
# pair is sanity-checked first (ARTIFACT_SPEC: "use the secondary anchors ... to sanity-check");
# anchors that fail are treated like missing anchors and use the fallback, which for bottoms
# scales the cutout's own waistband width to the avatar's hip width (upright, never stretched).
# A pair whose names are just in the reverse x-order (a naming swap, 6 of 9 bottoms) is fixed by
# swapping the labels -- not by mirroring the image or by a 180 deg rotation.
MAX_PAIR_TILT_DEG = 20.0
PAIR_WIDTH_FRAC = (0.30, 1.10)       # primary-pair distance / cutout width
ANCHOR_BOUNDS = (-0.30, 1.30)        # normalized x/y a primary anchor may take
BOTTOM_HIP_MAX_Y = 0.60              # a bottom's hips sit in its upper part
BOTTOM_KNEE_MIN_DROP = 0.10          # knees at least this far below hips (normalized)

# Fallback for bottoms: the waistband's pixel width lands at this multiple of the avatar's
# hip-JOINT distance (MediaPipe hips are joints, well inside the body outline). Human judgment
# call tuned by eye on the real avatars; not a measured constant.
WAISTBAND_TO_HIP_JOINT = 1.6
WAISTBAND_ROWS_FRAC = 0.04           # top slice of the garment's alpha bbox measured as waistband


def _oriented(anchors: dict[str, list[float]]) -> dict[str, list[float]]:
    """Front-facing convention (ARTIFACT_SPEC): left_* is on the image's right. If the hips (or,
    failing that, the shoulders) are in the opposite x-order, swap every left/right label."""
    for a, b in (("left_hip", "right_hip"), ("left_shoulder", "right_shoulder")):
        if a in anchors and b in anchors:
            if anchors[a][0] < anchors[b][0]:
                out = {}
                for name, v in anchors.items():
                    if name.startswith("left_"):
                        out["right_" + name[5:]] = v
                    elif name.startswith("right_"):
                        out["left_" + name[6:]] = v
                    else:
                        out[name] = v
                return out
            return anchors
    return anchors


def _anchors_plausible(anchors: dict[str, list[float]], names: tuple[str, str],
                       garment_type: GarmentType, w: int, h: int) -> bool:
    (x1, y1), (x2, y2) = anchors[names[0]], anchors[names[1]]
    lo, hi = ANCHOR_BOUNDS
    if not all(lo <= v <= hi for v in (x1, y1, x2, y2)):
        return False
    dx, dy = (x1 - x2) * w, (y1 - y2) * h
    if abs(math.degrees(math.atan2(dy, dx))) > MAX_PAIR_TILT_DEG:
        return False
    frac = math.hypot(dx, dy) / max(w, 1)
    if not PAIR_WIDTH_FRAC[0] <= frac <= PAIR_WIDTH_FRAC[1]:
        return False
    if garment_type in BOTTOM_TYPES:
        hip_y = (y1 + y2) / 2
        if hip_y > BOTTOM_HIP_MAX_Y:
            return False
        knees = [anchors[n][1] for n in ("left_knee", "right_knee") if n in anchors]
        if knees and sum(knees) / len(knees) < hip_y + BOTTOM_KNEE_MIN_DROP:
            return False
    return True


def _similarity_from_pair(src_pair, dst_pair) -> tuple[np.ndarray, np.ndarray]:
    """-> (A, T) such that dst = A @ src + T for the two given point pairs (forward transform)."""
    src1, src2 = np.array(src_pair[0], float), np.array(src_pair[1], float)
    dst1, dst2 = np.array(dst_pair[0], float), np.array(dst_pair[1], float)

    src_vec, dst_vec = src2 - src1, dst2 - dst1
    src_len = float(np.linalg.norm(src_vec)) or 1.0
    dst_len = float(np.linalg.norm(dst_vec)) or 1.0
    scale = dst_len / src_len
    theta = math.atan2(dst_vec[1], dst_vec[0]) - math.atan2(src_vec[1], src_vec[0])

    c, s = math.cos(theta), math.sin(theta)
    R = np.array([[c, -s], [s, c]])
    A = scale * R
    T = dst1 - A @ src1
    return A, T


def _pil_affine_data(A: np.ndarray, T: np.ndarray) -> tuple[float, float, float, float, float, float]:
    """PIL's AFFINE data maps OUTPUT pixel -> INPUT pixel, i.e. the inverse of (A, T)."""
    Ainv = np.linalg.inv(A)
    Tinv = -Ainv @ T
    return (Ainv[0, 0], Ainv[0, 1], Tinv[0], Ainv[1, 0], Ainv[1, 1], Tinv[1])


def _waist_point(rig: Rig, t: float) -> tuple[float, float]:
    """-> the point a fraction `t` of the way from the avatar's shoulder-mid to hip-mid (0 =
    shoulders, 1 = hips) -- where a bottom's waistband should land for a given rise."""
    sm, hm = rig.shoulder_mid, rig.hip_mid
    return (sm[0] + (hm[0] - sm[0]) * t, sm[1] + (hm[1] - sm[1]) * t)


def _bottom_rise_t(cutout: Image.Image, anchors: dict[str, list[float]]) -> float:
    """-> the WAIST_T fraction (see module docstring) this bottom's waistband should land at,
    inferred from its own anchors + cutout. Defaults to MID_RISE_WAIST_T whenever the hip/knee
    anchors are missing or degenerate -- never guesses low-rise, since that reproduces the
    old "everything at the hip line" bug for the common case."""
    required = ("left_hip", "right_hip", "left_knee", "right_knee")
    if not all(n in anchors for n in required):
        return MID_RISE_WAIST_T
    try:
        hip_y = (anchors["left_hip"][1] + anchors["right_hip"][1]) / 2.0
        knee_y = (anchors["left_knee"][1] + anchors["right_knee"][1]) / 2.0
        leg_span = knee_y - hip_y
        if leg_span <= 1e-6:
            return MID_RISE_WAIST_T

        alpha = np.array(cutout.convert("RGBA"))[:, :, 3]
        ys, _xs = np.where(alpha > 0)
        if ys.size == 0:
            return MID_RISE_WAIST_T
        waistband_y = ys.min() / cutout.height

        rise_ratio = (hip_y - waistband_y) / leg_span
    except Exception:
        return MID_RISE_WAIST_T

    if rise_ratio > RISE_HIGH_RATIO:
        return HIGH_RISE_WAIST_T
    if rise_ratio < RISE_LOW_RATIO:
        return LOW_RISE_WAIST_T
    return MID_RISE_WAIST_T


def _region_span(garment_type: GarmentType, rig: Rig) -> tuple[tuple[float, float], tuple[float, float]]:
    if garment_type in BOTTOM_TYPES:
        # No anchors at all to infer rise from (bbox fallback) -- default to mid-rise (see
        # _bottom_rise_t), not the raw hip line.
        top = _waist_point(rig, MID_RISE_WAIST_T)
        la, ra = rig.landmarks.get("left_ankle"), rig.landmarks.get("right_ankle")
        bottom = ((la[0] + ra[0]) / 2, (la[1] + ra[1]) / 2) if la and ra else rig.hip_mid
    else:
        top, bottom = rig.shoulder_mid, rig.hip_mid
    return top, bottom


def _bottom_width_fallback(cutout: Image.Image, rig: Rig) -> tuple[np.ndarray, np.ndarray]:
    """Bottoms without usable anchors: upright, waistband width = WAISTBAND_TO_HIP_JOINT x the
    avatar's hip width, waistband top centered on the avatar's mid-rise waist point."""
    alpha = np.array(cutout.convert("RGBA"))[:, :, 3] > 0
    ys, xs = np.where(alpha)
    if xs.size == 0 or rig.hip_width <= 0:
        return _bbox_fallback(cutout, GarmentType.pants, rig)
    y0, y1 = int(ys.min()), int(ys.max())
    # Row extents; skip thin stray bits at the top (hanger clips, belt loops) -- the waistband
    # starts at the first row at least half as wide as the garment's widest row.
    rows = alpha[y0:y1 + 1]
    has = rows.any(axis=1)
    left = np.where(has, rows.argmax(axis=1), 0)
    right = np.where(has, rows.shape[1] - rows[:, ::-1].argmax(axis=1), 0)
    widths = right - left
    start = int(np.argmax(widths >= 0.5 * widths.max()))
    n = max(1, round((y1 - y0 + 1) * WAISTBAND_ROWS_FRAC))
    sl = slice(start, start + n)
    band_x0, band_x1 = float(np.median(left[sl])), float(np.median(right[sl]))
    band_w = max(1.0, band_x1 - band_x0)
    y0 = y0 + start

    scale = WAISTBAND_TO_HIP_JOINT * rig.hip_width / band_w
    A = np.array([[scale, 0.0], [0.0, scale]])
    wx, wy = _waist_point(rig, MID_RISE_WAIST_T)
    target = np.array([rig.hip_mid[0], wy])
    T = target - A @ np.array([(band_x0 + band_x1) / 2.0, float(y0)])
    return A, T


def _bbox_fallback(cutout: Image.Image, garment_type: GarmentType, rig: Rig) -> tuple[np.ndarray, np.ndarray]:
    alpha = np.array(cutout.convert("RGBA"))[:, :, 3]
    ys, xs = np.where(alpha > 0)
    if xs.size == 0:
        bx0, by0, bx1, by1 = 0, 0, cutout.width, cutout.height
    else:
        bx0, by0, bx1, by1 = xs.min(), ys.min(), xs.max(), ys.max()
    bbox_h = max(1, by1 - by0)
    bbox_center = ((bx0 + bx1) / 2, (by0 + by1) / 2)

    top, bottom = _region_span(garment_type, rig)
    target_h = max(1.0, abs(bottom[1] - top[1]) * 1.15)
    target_center = ((top[0] + bottom[0]) / 2, (top[1] + bottom[1]) / 2)

    scale = target_h / bbox_h
    A = np.array([[scale, 0.0], [0.0, scale]])
    T = np.array(target_center) - A @ np.array(bbox_center)
    return A, T


def place_item(
    cutout: Image.Image,
    anchors: dict[str, list[float]],
    garment_type: GarmentType,
    rig: Rig,
    canvas_size: tuple[int, int],
) -> Image.Image:
    """-> an RGBA layer the size of `canvas_size` with the cutout placed on the rig."""
    names: Optional[tuple[str, str]] = PRIMARY_ANCHORS.get(garment_type)
    w, h = cutout.size

    usable = names is not None and all(n in anchors for n in names) and all(n in rig.landmarks for n in names)
    if usable:
        anchors = _oriented(anchors)
        usable = _anchors_plausible(anchors, names, garment_type, w, h)
        if not usable:
            print(f"avatar: implausible {garment_type.value} anchors {names}; using fallback")
    elif names is not None:
        print(f"avatar: placement fallback for {garment_type.value} -- missing anchor(s) {names}")

    if usable:
        n1, n2 = names
        src_pair = ((anchors[n1][0] * w, anchors[n1][1] * h), (anchors[n2][0] * w, anchors[n2][1] * h))
        dst_pair = (rig.landmarks[n1], rig.landmarks[n2])
        A, T = _similarity_from_pair(src_pair, dst_pair)

        if garment_type in BOTTOM_TYPES:
            # FE-2: shift vertically only (scale/rotation stay exactly as matched above) so the
            # waistband lands at this garment's own rise-appropriate point instead of always the
            # raw hip line.
            rise_t = _bottom_rise_t(cutout, anchors)
            target_y = _waist_point(rig, rise_t)[1]
            current_hip_y = (rig.landmarks[n1][1] + rig.landmarks[n2][1]) / 2.0
            T = T + np.array([0.0, target_y - current_hip_y])
    elif garment_type in BOTTOM_TYPES:
        A, T = _bottom_width_fallback(cutout, rig)
    else:
        print(f"avatar: placement fallback for {garment_type.value} -- bbox")
        A, T = _bbox_fallback(cutout, garment_type, rig)

    data = _pil_affine_data(A, T)
    return cutout.convert("RGBA").transform(
        canvas_size, Image.AFFINE, data, resample=Image.BICUBIC, fillcolor=(0, 0, 0, 0)
    )
