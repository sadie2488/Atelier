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
    region_mask = _box_mask(box, w, h)

    seg_result = image_segmenter().segment(mp_image)
    category = np.asarray(seg_result.category_mask.numpy_view())
    if category.ndim == 3:
        category = category[..., 0]
    clothes = category == CATEGORY_CLOTHES
    skin_mask = (category == CATEGORY_BODY_SKIN) | (category == CATEGORY_FACE_SKIN)
    non_background = category != CATEGORY_BACKGROUND

    base = clothes & region_mask

    variants = {name: _morph(base, radius) for name, radius in CANDIDATE_MORPH_RADIUS_PX.items()}

    # V-S2: independent extent for the completeness check -- pose region intersected with the
    # non-background signal, computed before skin exclusion, and never derived from `variants`.
    independent_extent_mask = region_mask & non_background

    return SegmentationResult(
        landmarks_px=points, region_box_px=box, variants=variants, multi_person=multi_person,
        skin_mask=skin_mask, independent_extent_mask=independent_extent_mask,
    )
