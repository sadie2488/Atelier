"""A4: garments placed via a similarity transform from cutout anchors to avatar rig landmarks
(contract/ARTIFACT_SPEC.md). Uniform scale + rotation + translation only -- garments are never
stretched non-uniformly. An item missing a required anchor falls back to its alpha bounding box
aligned to the avatar's landmark span for that region; logged, never fails the render.
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


def _region_span(garment_type: GarmentType, rig: Rig) -> tuple[tuple[float, float], tuple[float, float]]:
    if garment_type in (GarmentType.pants, GarmentType.skirt, GarmentType.shorts):
        top = rig.hip_mid
        la, ra = rig.landmarks.get("left_ankle"), rig.landmarks.get("right_ankle")
        bottom = ((la[0] + ra[0]) / 2, (la[1] + ra[1]) / 2) if la and ra else rig.hip_mid
    else:
        top, bottom = rig.shoulder_mid, rig.hip_mid
    return top, bottom


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
        n1, n2 = names
        src_pair = ((anchors[n1][0] * w, anchors[n1][1] * h), (anchors[n2][0] * w, anchors[n2][1] * h))
        dst_pair = (rig.landmarks[n1], rig.landmarks[n2])
        A, T = _similarity_from_pair(src_pair, dst_pair)
    else:
        print(f"avatar: placement fallback for {garment_type.value} -- missing anchor(s) {names}")
        A, T = _bbox_fallback(cutout, garment_type, rig)

    data = _pil_affine_data(A, T)
    return cutout.convert("RGBA").transform(
        canvas_size, Image.AFFINE, data, resample=Image.BICUBIC, fillcolor=(0, 0, 0, 0)
    )
