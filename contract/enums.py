"""Atelier contract v2: enums and shared thresholds. HUMAN-OWNED.

Every agent reads this; no agent edits it. Changes go through the PM, both humans agree,
bump CONTRACT_VERSION in schemas.py, and push immediately.
"""
from enum import Enum


class Category(str, Enum):
    """Which swipe list an item lands in and how outfit assembly treats it."""
    tops = "tops"
    bottoms = "bottoms"
    jackets = "jackets"


class GarmentType(str, Enum):
    """Which pose region vision segments. A dress is category tops, garment_type dress."""
    shirt = "shirt"
    dress = "dress"
    pants = "pants"
    skirt = "skirt"
    shorts = "shorts"
    jacket = "jacket"
    coat = "coat"


# Amendment A1: the only permitted (category, garment_type) pairs.
VALID_PAIRS: dict[Category, frozenset[GarmentType]] = {
    Category.tops: frozenset({GarmentType.shirt, GarmentType.dress}),
    Category.bottoms: frozenset({GarmentType.pants, GarmentType.skirt, GarmentType.shorts}),
    Category.jackets: frozenset({GarmentType.jacket, GarmentType.coat}),
}

# V-A2: item slug prefix, "<prefix>_<6 lowercase hex>", e.g. top_a3f9c2, dress_7b1e04.
SLUG_PREFIX: dict[GarmentType, str] = {
    GarmentType.shirt: "top",
    GarmentType.dress: "dress",
    GarmentType.pants: "bottom",
    GarmentType.skirt: "bottom",
    GarmentType.shorts: "bottom",
    GarmentType.jacket: "jacket",
    GarmentType.coat: "jacket",
}


class Strategy(str, Enum):
    """S-S2 outfit strategies, in degradation-ladder order."""
    neutral_anchor = "neutral_anchor"
    everyday_neutral_base = "everyday_neutral_base"
    analogous = "analogous"
    complementary = "complementary"
    monochrome_highlight = "monochrome_highlight"
    sandwich = "sandwich"               # requires a jacket


class RenderStatus(str, Enum):
    pending = "pending"
    done = "done"
    failed = "failed"


class CandidateVariant(str, Enum):
    """V-S3: the three analyze candidates, in index order 0, 1, 2."""
    tight = "tight"
    balanced = "balanced"
    generous = "generous"


class ErrorCode(str, Enum):
    invalid_request = "invalid_request"          # bad field, invalid category/garment_type pair, too large
    not_found = "not_found"                      # unknown slug, avatar_id, render_id
    pose_rejected = "pose_rejected"              # avatar scan: message is the actionable reason
    no_person_detected = "no_person_detected"    # analyze or avatar scan found nobody
    unsupported_image = "unsupported_image"      # not JPEG/PNG/WebP, or undecodable
    analyze_failed = "analyze_failed"            # segmentation raised
    handle_expired = "handle_expired"            # temp_handle unknown, used, or swept
    gemini_unavailable = "gemini_unavailable"
    not_implemented = "not_implemented"          # 501 from a route a lane hasn't built yet
    internal_error = "internal_error"            # any lane: unexpected internal failure (500), never a bare stack trace


# ---- Shared thresholds (one source of truth for pipeline, scorer, and tests) ----

IMAGE_LONG_SIDE_PX = 1024          # preprocess resizes the long side to this
MAX_UPLOAD_BYTES = 12 * 1024 * 1024  # V-E5
CANDIDATE_COUNT = 3                # V-E1: analyze always returns exactly three

COLOR_KMEANS_K = 5                 # V-C2: k-means in CIELAB over alpha > 0 pixels
SECONDARY_MIN_MASS = 0.20          # V-C3: later cluster needs >= 20% of masked pixels
SECONDARY_MIN_DELTA_E = 20.0       # V-C3: ... and >= this CIEDE2000 from the primary
MAX_ASSIGNMENT_DELTA_E = 25.0      # V-C4: must equal colors.json max_assignment_delta_e
UNMAPPED = "unmapped"              # V-C4: name and family beyond MAX_ASSIGNMENT_DELTA_E
NEUTRAL_CHROMA_MAX = 12.0          # V-C5: is_neutral == (LCh chroma < this)

OUTFITS_MAX = 5                    # S-L1
OUTFITS_MAX_PER_STRATEGY = 2       # S-L1
OUTFITS_MAX_SHARING_GARMENT = 2    # S-L1; jackets exempt
