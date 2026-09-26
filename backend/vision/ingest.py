"""Orchestrates V1-V4 for one analyze call: bytes -> three candidate cutouts with color and
anchors. V-S3: a single segmentation+pose pass; the three candidates differ only in
post-processing (already handled by segmentation.segment's `variants`).
"""
from contract.enums import CandidateVariant, Category, GarmentType

from .artifact import build_cutout
from .checks import run_checks
from .color import extract_colors
from .preprocess import load_and_normalize
from .segmentation import segment

_VARIANT_ORDER = [CandidateVariant.tight, CandidateVariant.balanced, CandidateVariant.generous]

# V-S7: garment types worn on the upper vs. lower body, for the cheap category/pose-region
# mismatch signal below. A dress is excluded -- it legitimately spans both regions (V-S5), so
# "more clothes mass below the hip than above it" is expected, not a mismatch.
_TOP_WORN = {GarmentType.shirt, GarmentType.jacket, GarmentType.coat}
_BOTTOM_WORN = {GarmentType.pants, GarmentType.skirt, GarmentType.shorts}

# Require the "other" region to clearly dominate, not just edge it out, before logging -- this is
# an informational signal (never a rejection, per V-S7), so a modest false-negative rate here
# costs nothing while a noisy one would just add junk to the failure log.
_MISMATCH_RATIO = 1.5
_MISMATCH_FLOOR_PX = 2000


def _category_mismatch(category: Category, garment_type: GarmentType, top_mass: int, bottom_mass: int) -> bool:
    if garment_type in _TOP_WORN:
        return bottom_mass > _MISMATCH_FLOOR_PX and bottom_mass > _MISMATCH_RATIO * max(top_mass, 1)
    if garment_type in _BOTTOM_WORN:
        return top_mass > _MISMATCH_FLOOR_PX and top_mass > _MISMATCH_RATIO * max(bottom_mass, 1)
    return False  # dress: both regions are expected to carry mass


def build_candidates(
    image_bytes: bytes, category: Category, garment_type: GarmentType,
) -> tuple[list[dict], bool, bool]:
    """-> (list of 3 candidate dicts in tight/balanced/generous order, multi_person,
    category_mismatch).

    Each candidate dict: variant (CandidateVariant), rgba (HxWx4 uint8 ndarray), anchors
    ({name: [x, y]}), primary_color (dict), secondary_color (dict | None), checks (dict).
    """
    rgb = load_and_normalize(image_bytes)
    seg = segment(rgb, garment_type)
    mismatch = _category_mismatch(category, garment_type, seg.top_region_mass, seg.bottom_region_mass)

    candidates = []
    for variant in _VARIANT_ORDER:
        mask = seg.variants[variant.value]
        rgba, anchors = build_cutout(rgb, mask, seg.landmarks_px, garment_type)
        primary, secondary = extract_colors(rgba)
        checks = run_checks(mask, seg.skin_mask, seg.independent_extent_mask, rgba[..., 3] > 0, category)
        candidates.append({
            "variant": variant,
            "rgba": rgba,
            "anchors": anchors,
            "primary_color": primary,
            "secondary_color": secondary,
            "checks": checks,
        })

    return candidates, seg.multi_person, mismatch
