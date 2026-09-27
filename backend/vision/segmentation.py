"""V2 isolation: one MediaPipe person-segmentation + pose pass, three candidate masks.

V-S1: skin is excluded by MediaPipe's multiclass category (never HSV/RGB thresholding) --
the "clothes" category (4) is disjoint from "body-skin" (2) and "face-skin" (3) by
construction, so masking to category==4 already keeps skin out.

V-S5: the pose region (which part of the body the garment could occupy) is selected by
garment_type, not category -- a dress needs a continuous shoulder-to-ankle span.

V-S6: with more than one person in frame, take the largest and log `multi_person` (the caller
does the logging; this module just reports `multi_person`). "Largest" is approximated by
landmark bounding-box area rather than segmentation mask area -- see mp_models.pose_landmarker
for why (a mediapipe/Windows bug in PoseLandmarker's own mask output, not a design choice).

V-S7 (mismatch signal): `top_region_mass`/`bottom_region_mass` are the clothes-category pixel
counts inside the two canonical shoulder-to-hip / hip-to-ankle boxes, computed independently of
`garment_type`. The caller (ingest.build_candidates) compares these against the user's declared
category -- this module only reports the two masses.

V6: `base` (clothes-category ∩ pose-region ∩ largest-person) is restricted to its largest
connected component before the per-variant erosion/dilation. Diagnosed against fixtures/images
via backend/vision/scripts/eval_fixtures.py: several color-family misses on the balanced
candidate came from a second, smaller "clothes" blob touching the frame edge inside the padded
region box -- a strip of jeans below a cropped top (the hip landmark sits below a fitted top's
hem, so REGION_PAD_FRACTION still reaches the waistband), or a belt at the hip -- which pulled a
k-means cluster toward that blob's color. Keeping only the largest component removes these
without any color thresholding.

V6 isolation (re-dispatch): the `clothes` category is one class for every garment a model is
wearing at once -- it does not distinguish a jacket from the tank top and skirt underneath it,
so on a multi-garment photo `base` is a single connected blob spanning all of them (largest
connected component alone cannot split them; they are physically touching). Two fixes, applied
in order:
  1. `_region_box` now pads asymmetrically per garment_type (`candidate_params.REGION_PAD`):
     generous on the garment's own far edge, tight on the edge shared with a neighboring
     garment (the hip line, for a top vs. a bottom), so less of the neighbor enters `base` to
     begin with.
  2. `_isolate_by_color` then splits whatever `clothes` pixels remain in `base` into
     color-coherent segments (k-means in Lab, same approach as V4's own color extraction) and
     keeps only the segment(s) that dominate a small "core probe" band placed over where the
     requested garment_type is expected to be found (torso center for tops/dress, just below
     the shoulders for jacket/coat -- a jacket worn open still closes there even though it
     exposes an inner layer lower down -- upper thigh for pants/skirt/shorts). A same-colored
     trim/pattern segment that happens to dominate the probe is kept in full; an unrelated
     garment's segment is dropped even though it was 4-connected to the kept one.
Neither step touches skin exclusion (still MediaPipe categories only, V-S1) or uses color to
detect skin -- only to separate garments that the segmenter itself does not distinguish.
"""
from dataclasses import dataclass

import numpy as np
from scipy import ndimage
from skimage.color import rgb2lab
from sklearn.cluster import KMeans

from contract.enums import ErrorCode, GarmentType
from contract.tools.color import delta_e2000

from . import VisionError
from .candidate_params import (
    CANDIDATE_MORPH_RADIUS_PX, CORE_PROBE_BAND, CORE_PROBE_MIN_COVERAGE, ISOLATION_KMEANS_K,
    ISOLATION_MIN_PIXELS, ISOLATION_SAMPLE_PIXELS, PATTERN_BOUNDARY_CONTACT_MIN,
    PATTERN_CLOSING_RADIUS_PX, PATTERN_MAX_COMPONENT_FRAC, PATTERN_RING_PX, REGION_PAD,
    REGION_PAD_FRACTION, SAME_FABRIC_MAX_DELTA_E, SECONDARY_MAX_AREA_RATIO,
)
from .mp_models import CATEGORY_BACKGROUND, CATEGORY_BODY_SKIN, CATEGORY_CLOTHES, CATEGORY_FACE_SKIN, image_segmenter, pose_landmarker

# MediaPipe BlazePose 33-point indices, person's own left/right (ARTIFACT_SPEC naming).
LM = {
    "left_shoulder": 11, "right_shoulder": 12,
    "left_elbow": 13, "right_elbow": 14,
    "left_wrist": 15, "right_wrist": 16,
    "left_hip": 23, "right_hip": 24,
    "left_knee": 25, "right_knee": 26,
    "left_ankle": 27, "right_ankle": 28,
}

# V-S5: which landmarks bound the pose region per garment_type.
_REGION_LANDMARKS: dict[GarmentType, list[str]] = {
    GarmentType.shirt: ["left_shoulder", "right_shoulder", "left_hip", "right_hip"],
    GarmentType.jacket: ["left_shoulder", "right_shoulder", "left_hip", "right_hip",
                         "left_wrist", "right_wrist"],
    GarmentType.coat: ["left_shoulder", "right_shoulder", "left_hip", "right_hip",
                       "left_wrist", "right_wrist"],
    GarmentType.dress: ["left_shoulder", "right_shoulder", "left_hip", "right_hip",
                        "left_ankle", "right_ankle"],
    GarmentType.pants: ["left_hip", "right_hip", "left_knee", "right_knee",
                        "left_ankle", "right_ankle"],
    GarmentType.skirt: ["left_hip", "right_hip", "left_knee", "right_knee",
                        "left_ankle", "right_ankle"],
    GarmentType.shorts: ["left_hip", "right_hip", "left_knee", "right_knee",
                         "left_ankle", "right_ankle"],
}

# Public alias: ARTIFACT_SPEC's required-anchor table is the same landmark sets as the
# segmentation region (V3 stores these normalized per cutout).
ANCHOR_LANDMARKS = _REGION_LANDMARKS


@dataclass
class SegmentationResult:
    landmarks_px: dict[str, tuple[float, float]]   # ALL named landmarks, pixel coords, this person
    region_box_px: tuple[float, float, float, float]  # x0, y0, x1, y1 used to build the region mask
    variants: dict[str, np.ndarray]                # variant name -> HxW bool mask
    multi_person: bool
    skin_mask: np.ndarray                          # V-S1: MediaPipe body-skin | face-skin categories
    independent_extent_mask: np.ndarray            # V-S2: pose region & non-background, pre-skin-exclusion
    top_region_mass: int                           # V-S7: clothes px in the canonical shoulder-hip box
    bottom_region_mass: int                        # V-S7: clothes px in the canonical hip-ankle box


def _landmark_dict(pose_landmarks, w: int, h: int) -> dict[str, tuple[float, float]]:
    return {name: (pose_landmarks[idx].x * w, pose_landmarks[idx].y * h) for name, idx in LM.items()}


def _region_box(
    points: dict[str, tuple[float, float]], names: list[str], w: int, h: int,
    pad_top: float = REGION_PAD_FRACTION, pad_bottom: float = REGION_PAD_FRACTION,
    pad_x: float = REGION_PAD_FRACTION,
):
    """`pad_top`/`pad_bottom`/`pad_x` are fractions of the landmark span (V-S5 tightening):
    asymmetric so a garment's region can stay generous on its own far edge while staying tight
    on the edge it shares with a neighboring garment. Defaults keep the old symmetric behavior
    for callers (the V-S7 canonical mismatch-signal boxes) that don't need per-edge control."""
    xs = [points[n][0] for n in names]
    ys = [points[n][1] for n in names]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    span_x = max(x1 - x0, 1.0)
    span_y = max(y1 - y0, 1.0)
    return (
        max(0.0, x0 - pad_x * span_x), max(0.0, y0 - pad_top * span_y),
        min(float(w), x1 + pad_x * span_x), min(float(h), y1 + pad_bottom * span_y),
    )


def _box_mask(box, w: int, h: int) -> np.ndarray:
    x0, y0, x1, y1 = box
    mask = np.zeros((h, w), dtype=bool)
    mask[int(round(y0)):int(round(y1)), int(round(x0)):int(round(x1))] = True
    return mask


def _fill_small_holes(mask: np.ndarray, max_frac: float = 0.02) -> np.ndarray:
    """Fills only holes that would pass V-Q2's own completeness_holes_le_2pct bar (a button, a
    gap between crossed straps) -- unlike unconditional `binary_fill_holes`, a LARGE enclosed
    hole (an open jacket's exposed midriff, fully surrounded by jacket fabric in a lucky pose)
    is left transparent rather than silently patched over with whatever is beneath it."""
    if not mask.any():
        return mask
    filled = ndimage.binary_fill_holes(mask)
    holes = filled & ~mask
    if not holes.any():
        return mask
    total = mask.sum()
    labeled, n = ndimage.label(holes)
    out = mask.copy()
    for i in range(1, n + 1):
        comp = labeled == i
        if comp.sum() <= max_frac * total:
            out |= comp
    return out


def _morph(mask: np.ndarray, radius_px: int) -> np.ndarray:
    out = mask
    if radius_px > 0:
        out = ndimage.binary_dilation(out, iterations=radius_px)
    elif radius_px < 0:
        out = ndimage.binary_erosion(out, iterations=-radius_px)
    return _fill_small_holes(out)


def _largest_component(mask: np.ndarray) -> np.ndarray:
    """Keep only the largest 4-connected component. V6: drops smaller disconnected `clothes`
    blobs (a strip of a second garment, a belt, a stray misclassified patch) that would
    otherwise skew k-means color extraction (V-C2) toward a color the target garment doesn't
    actually have. Returns an all-False mask unchanged (nothing to filter)."""
    labeled, n = ndimage.label(mask)
    if n <= 1:
        return mask
    counts = np.bincount(labeled.ravel())
    counts[0] = 0
    return labeled == int(np.argmax(counts))


def _core_probe_mask(
    garment_type: GarmentType, points: dict[str, tuple[float, float]], w: int, h: int,
) -> np.ndarray:
    """V6 isolation: a small band, positioned per garment_type, over where the requested
    garment is expected to dominate even when another garment/layer is also in frame -- see
    `_isolate_by_color` and `candidate_params.CORE_PROBE_BAND`."""
    if garment_type in (GarmentType.pants, GarmentType.skirt, GarmentType.shorts):
        top_names, bottom_names, x_names = (
            ["left_hip", "right_hip"], ["left_ankle", "right_ankle"],
            ["left_hip", "right_hip", "left_knee", "right_knee"],
        )
    elif garment_type == GarmentType.dress:
        top_names, bottom_names, x_names = (
            ["left_shoulder", "right_shoulder"], ["left_ankle", "right_ankle"],
            ["left_shoulder", "right_shoulder"],
        )
    else:  # shirt, jacket, coat
        top_names, bottom_names, x_names = (
            ["left_shoulder", "right_shoulder"], ["left_hip", "right_hip"],
            ["left_shoulder", "right_shoulder"],
        )
    top_y = min(points[n][1] for n in top_names)
    bottom_y = max(points[n][1] for n in bottom_names)
    span = max(bottom_y - top_y, 1.0)
    frac0, frac1 = CORE_PROBE_BAND[garment_type.value]
    xs = [points[n][0] for n in x_names]
    box = (min(xs), top_y + frac0 * span, max(xs), top_y + frac1 * span)
    return _box_mask(box, w, h)


def _drop_tiny_components(mask: np.ndarray, min_px: int) -> np.ndarray:
    """Keeps every connected component at or above `min_px`, dropping only noise-sized flecks.
    Unlike `_largest_component`, this can keep more than one component."""
    labeled, n = ndimage.label(mask)
    if n <= 1:
        return mask
    counts = np.bincount(labeled.ravel())
    counts[0] = 0
    keep = np.zeros(n + 1, dtype=bool)
    keep[1:] = counts[1:] >= min_px
    return keep[labeled]


def _pattern_fragments(dropped_mask: np.ndarray, kept_mask: np.ndarray, anchor_area: int) -> np.ndarray:
    """V6.1 isolation (re-dispatch): of a cluster already rejected by the SAME_FABRIC/area-ratio
    tests in `_isolate_by_color`, recover the individual connected components that are actually a
    same-garment PATTERN interleaved with the kept fabric, rather than a competing garment --
    see `candidate_params.PATTERN_MAX_COMPONENT_FRAC`'s docstring for the two-part test and how
    it was tuned. Operates per connected component (not the whole cluster) since one cluster can
    mix harmless same-garment specular highlights with a single genuine competing-garment piece
    in a similar color."""
    labeled, n = ndimage.label(dropped_mask)
    if n == 0:
        return np.zeros_like(dropped_mask)
    keep = np.zeros_like(dropped_mask)
    max_px = PATTERN_MAX_COMPONENT_FRAC * max(anchor_area, 1)
    for i in range(1, n + 1):
        comp = labeled == i
        comp_px = int(comp.sum())
        if comp_px == 0 or comp_px > max_px:
            continue  # forms its own large contiguous region -- a competing garment, not a pattern
        ring = ndimage.binary_dilation(comp, iterations=PATTERN_RING_PX) & ~comp
        ring_total = int(ring.sum())
        if ring_total == 0:
            continue
        boundary_contact = float((ring & kept_mask).sum()) / ring_total
        if boundary_contact >= PATTERN_BOUNDARY_CONTACT_MIN:
            keep |= comp
    return keep


def _isolate_by_color(rgb: np.ndarray, base: np.ndarray, core_probe: np.ndarray) -> np.ndarray:
    """V6 isolation: splits `base` (clothes ∩ pose-region ∩ largest-person, already restricted
    to its largest connected component) into color-coherent segments and keeps only the ones
    that dominate `core_probe` -- see this module's docstring for why (the `clothes` category
    does not distinguish one garment from another). Falls back to returning `base` unchanged
    whenever there isn't enough signal to safely split it (too few pixels, degenerate probe, or
    a k-means fit that finds no acceptable segment)."""
    total = int(base.sum())
    if total < ISOLATION_MIN_PIXELS:
        return base

    ys, xs = np.where(base)
    px = rgb[ys, xs].astype(np.float64) / 255.0
    lab = rgb2lab(px.reshape(-1, 1, 3)).reshape(-1, 3)

    rng = np.random.default_rng(0)
    if len(lab) > ISOLATION_SAMPLE_PIXELS:
        fit_lab = lab[rng.choice(len(lab), ISOLATION_SAMPLE_PIXELS, replace=False)]
    else:
        fit_lab = lab
    k = max(1, min(ISOLATION_KMEANS_K, len(np.unique(fit_lab.round(1), axis=0))))
    if k == 1:
        return base

    km = KMeans(n_clusters=k, n_init=4, random_state=0).fit(fit_lab)
    labels = km.predict(lab)

    label_img = np.full(rgb.shape[:2], -1, dtype=np.int16)
    label_img[ys, xs] = labels

    core_total = int(core_probe.sum())
    if core_total == 0:
        return base

    cluster_area = {cid: int((label_img == cid).sum()) for cid in range(k)}
    coverage = [
        (float(((label_img == cid) & core_probe).sum()) / core_total, cid)
        for cid in range(k)
    ]
    coverage.sort(reverse=True)

    # The best-covering cluster anchors the garment. Every other cluster is judged one of two
    # ways:
    #  - Lab-close to the anchor (within SAME_FABRIC_MAX_DELTA_E) -> the SAME fabric, just a
    #    different shade from folds/lighting across the garment (very common in retail photos,
    #    and can easily be half the garment's area) -- always kept, no area/coverage test.
    #  - Lab-far from the anchor -> a genuinely different color. Kept only if it still
    #    meaningfully covers the core probe AND is a minority of the anchor's own area -- a
    #    patterned trim/yoke is a minor fraction of its garment's fabric, whereas a competing
    #    garment (an inner tank top under an open jacket) is typically comparable in area to
    #    what's left of the outer one, not a minor accent, so this drops it even though it also
    #    reaches into the (deliberately wide) core probe.
    anchor_cid = coverage[0][1]
    anchor_lab = tuple(km.cluster_centers_[anchor_cid])
    keep_ids = [anchor_cid]
    anchor_area = max(cluster_area[anchor_cid], 1)
    for cov, cid in coverage[1:]:
        if delta_e2000(tuple(km.cluster_centers_[cid]), anchor_lab) < SAME_FABRIC_MAX_DELTA_E:
            keep_ids.append(cid)
        elif cov >= CORE_PROBE_MIN_COVERAGE and cluster_area[cid] <= SECONDARY_MAX_AREA_RATIO * anchor_area:
            keep_ids.append(cid)

    isolated = np.isin(label_img, keep_ids) & base

    # V6.1 isolation (re-dispatch): rescue same-garment PATTERN fragments (a Fair Isle yoke's
    # colorwork) that the SAME_FABRIC/area-ratio rules above wrongly dropped whole-cluster -- see
    # `_pattern_fragments` and `candidate_params.PATTERN_MAX_COMPONENT_FRAC`.
    dropped_mask = np.isin(label_img, [cid for cid in range(k) if cid not in keep_ids]) & base
    if dropped_mask.any():
        isolated = isolated | _pattern_fragments(dropped_mask, isolated, anchor_area)

    # Bridge hairline gaps left between rescued pattern fragments and the kept fabric (see
    # `candidate_params.PATTERN_CLOSING_RADIUS_PX`), bounded so closing can never grow the mask
    # past the clothes-category evidence already in `base`.
    if isolated.any() and PATTERN_CLOSING_RADIUS_PX > 0:
        closed = ndimage.binary_dilation(isolated, iterations=PATTERN_CLOSING_RADIUS_PX)
        closed = ndimage.binary_erosion(closed, iterations=PATTERN_CLOSING_RADIUS_PX)
        closed &= ndimage.binary_dilation(base, iterations=PATTERN_CLOSING_RADIUS_PX)
        isolated = _fill_small_holes(closed | isolated)

    # Not `_largest_component` again here: an open jacket's kept (anchor) cluster can be two
    # genuinely disconnected panels (the tank top between them was the OTHER cluster, already
    # excluded above) -- collapsing to one connected blob would throw away a whole real lapel.
    # Just drop small flecks: noise-sized fragments of a kept cluster scattered elsewhere in the
    # region (e.g. a stray pixel or two the segmenter mis-classified).
    isolated = _drop_tiny_components(isolated, min_px=max(50, int(0.005 * total)))
    return isolated if isolated.any() else base


def segment(rgb: np.ndarray, garment_type: GarmentType) -> SegmentationResult:
    import mediapipe as mp

    h, w = rgb.shape[:2]
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

    pose_result = pose_landmarker().detect(mp_image)
    if not pose_result.pose_landmarks:
        raise VisionError(
            ErrorCode.no_person_detected,
            "No person found in the photo. Use a retail photo of the garment worn by a model.",
        )

    multi_person = len(pose_result.pose_landmarks) > 1
    # V-S6: no per-person segmentation mask is available here (see mp_models.pose_landmarker),
    # so "largest person" is approximated by full-body landmark bounding-box area.
    all_points = [_landmark_dict(lm, w, h) for lm in pose_result.pose_landmarks]
    areas = []
    for pts in all_points:
        xs = [p[0] for p in pts.values()]
        ys = [p[1] for p in pts.values()]
        areas.append((max(xs) - min(xs)) * (max(ys) - min(ys)))
    chosen = int(np.argmax(areas))

    points = all_points[chosen]
    region_names = _REGION_LANDMARKS[garment_type]
    pad_top, pad_bottom, pad_x = REGION_PAD[garment_type.value]
    box = _region_box(points, region_names, w, h, pad_top=pad_top, pad_bottom=pad_bottom, pad_x=pad_x)
    if box[2] <= box[0] or box[3] <= box[1]:
        # V6: a tight product-photo crop (e.g. waist-to-mid-thigh only) can leave BlazePose with
        # near-zero presence for the landmarks a pose region needs (hip/knee/ankle extrapolated
        # far below the frame -- confirmed by probe against fixtures/images), which inverts
        # min/max into a degenerate box. There is no usable pose constraint in that case, so fall
        # back to the whole frame; `clothes` category still excludes background/skin/hair.
        box = (0.0, 0.0, float(w), float(h))
    region_mask = _box_mask(box, w, h)

    seg_result = image_segmenter().segment(mp_image)
    category = np.asarray(seg_result.category_mask.numpy_view())
    if category.ndim == 3:
        category = category[..., 0]
    clothes = category == CATEGORY_CLOTHES
    skin_mask = (category == CATEGORY_BODY_SKIN) | (category == CATEGORY_FACE_SKIN)
    non_background = category != CATEGORY_BACKGROUND

    base = _largest_component(clothes & region_mask)
    if box[2] > box[0] and box[3] > box[1]:
        # V6 isolation: only probe/split when the region box is a real pose-derived box, not
        # the degenerate-fallback whole frame (a core probe over the whole image isn't a useful
        # signal -- see the box-degeneracy comment above).
        core_probe = _core_probe_mask(garment_type, points, w, h)
        base = _isolate_by_color(rgb, base, core_probe)

    variants: dict[str, np.ndarray] = {}
    for name, radius in CANDIDATE_MORPH_RADIUS_PX.items():
        m = _morph(base, radius)
        # V6: an erosion radius can hollow out a small/thin garment to nothing (e.g. the
        # "tight" variant on a short pair of shorts). Step back toward radius 0 rather than
        # handing build_cutout an empty mask -- a genuine no-garment case still fails, just
        # later, when even the unmorphed `base` is empty.
        r = radius
        while not m.any() and r < 0:
            r += 1
            m = _morph(base, r)
        variants[name] = m

    # V-S2: independent extent for the completeness check -- pose region intersected with the
    # non-background signal, computed before skin exclusion, and never derived from `variants`.
    independent_extent_mask = region_mask & non_background

    # V-S7: canonical top/bottom spans, independent of garment_type, to let the caller flag a
    # declared category that disagrees with what's actually in frame. Reuses the shirt (shoulder-
    # hip) and pants (hip-ankle) landmark sets as the two canonical halves -- cheap, no extra
    # model pass, since `clothes`/`points` are already computed above.
    top_box = _region_box(points, _REGION_LANDMARKS[GarmentType.shirt], w, h)
    bottom_box = _region_box(points, _REGION_LANDMARKS[GarmentType.pants], w, h)
    top_region_mass = int((clothes & _box_mask(top_box, w, h)).sum())
    bottom_region_mass = int((clothes & _box_mask(bottom_box, w, h)).sum())

    return SegmentationResult(
        landmarks_px=points, region_box_px=box, variants=variants, multi_person=multi_person,
        skin_mask=skin_mask, independent_extent_mask=independent_extent_mask,
        top_region_mass=top_region_mass, bottom_region_mass=bottom_region_mass,
    )
