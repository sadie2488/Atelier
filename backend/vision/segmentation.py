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
"""
from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from contract.enums import ErrorCode, GarmentType

from . import VisionError
from .candidate_params import CANDIDATE_MORPH_RADIUS_PX, REGION_PAD_FRACTION
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


def _region_box(points: dict[str, tuple[float, float]], names: list[str], w: int, h: int):
    xs = [points[n][0] for n in names]
    ys = [points[n][1] for n in names]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    pad_x = REGION_PAD_FRACTION * max(x1 - x0, 1.0)
    pad_y = REGION_PAD_FRACTION * max(y1 - y0, 1.0)
    return (
        max(0.0, x0 - pad_x), max(0.0, y0 - pad_y),
        min(float(w), x1 + pad_x), min(float(h), y1 + pad_y),
    )


def _box_mask(box, w: int, h: int) -> np.ndarray:
    x0, y0, x1, y1 = box
    mask = np.zeros((h, w), dtype=bool)
    mask[int(round(y0)):int(round(y1)), int(round(x0)):int(round(x1))] = True
    return mask


def _morph(mask: np.ndarray, radius_px: int) -> np.ndarray:
    out = mask
    if radius_px > 0:
        out = ndimage.binary_dilation(out, iterations=radius_px)
    elif radius_px < 0:
        out = ndimage.binary_erosion(out, iterations=-radius_px)
    return ndimage.binary_fill_holes(out)


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
    box = _region_box(points, region_names, w, h)
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
