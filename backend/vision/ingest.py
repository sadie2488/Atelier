"""Orchestrates V1-V4 for one analyze call: bytes -> three candidate cutouts with color and
anchors. V-S3: a single segmentation+pose pass; the three candidates differ only in
post-processing (already handled by segmentation.segment's `variants`).
"""
from contract.enums import CandidateVariant, GarmentType

from .artifact import build_cutout
from .checks import run_checks
from .color import extract_colors
from .preprocess import load_and_normalize
from .segmentation import segment

_VARIANT_ORDER = [CandidateVariant.tight, CandidateVariant.balanced, CandidateVariant.generous]


def build_candidates(image_bytes: bytes, garment_type: GarmentType) -> tuple[list[dict], bool]:
    """-> (list of 3 candidate dicts in tight/balanced/generous order, multi_person).

    Each candidate dict: variant (CandidateVariant), rgba (HxWx4 uint8 ndarray), anchors
    ({name: [x, y]}), primary_color (dict), secondary_color (dict | None), checks (dict).
    """
    rgb = load_and_normalize(image_bytes)
    seg = segment(rgb, garment_type)

    candidates = []
    for variant in _VARIANT_ORDER:
        mask = seg.variants[variant.value]
        rgba, anchors = build_cutout(rgb, mask, seg.landmarks_px, garment_type)
        primary, secondary = extract_colors(rgba)
        checks = run_checks(mask, seg.skin_mask, seg.independent_extent_mask, rgba[..., 3] > 0)
        candidates.append({
            "variant": variant,
            "rgba": rgba,
            "anchors": anchors,
            "primary_color": primary,
            "secondary_color": secondary,
            "checks": checks,
        })

    return candidates, seg.multi_person
