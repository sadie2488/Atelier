"""Closet app contract: enums and shared thresholds. HUMAN-OWNED (lane A).

Every agent reads this; no agent edits it. Change it only on the lane A laptop,
agree with lane B, bump CONTRACT_VERSION in schemas.py, and push immediately.
"""
from enum import Enum


class Category(str, Enum):
    top = "top"
    bottom = "bottom"
    dress = "dress"
    outerwear = "outerwear"
    shoes = "shoes"
    accessory = "accessory"


class Pattern(str, Enum):
    solid = "solid"
    stripe = "stripe"
    plaid = "plaid"
    floral = "floral"
    graphic = "graphic"
    other = "other"


class Ownership(str, Enum):
    owned = "owned"
    catalog = "catalog"


class Source(str, Enum):
    scan = "scan"          # waist-up camera capture, clothing segmentation
    flatlay = "flatlay"    # photo upload of one garment, background removal


class GarmentStatus(str, Enum):
    ready = "ready"                  # fully processed and classified
    needs_review = "needs_review"    # classification failed twice; user must set the category
    failed = "failed"                # processing failed; not usable in outfits


class HeadSource(str, Enum):
    generated = "generated"            # drawn head from Gemini image generation
    photo_fallback = "photo_fallback"  # face photo cut out, used when generation fails


class ReasonSource(str, Enum):
    llm = "llm"            # reason written by the Gemini re-rank
    template = "template"  # fallback reason built from the score breakdown


class SegmentClass(str, Enum):
    """Garment classes the clothing segmenter can return for a scan."""
    upper_clothes = "upper_clothes"
    coat = "coat"
    dress = "dress"
    pants = "pants"
    skirt = "skirt"
    other = "other"


class ErrorCode(str, Enum):
    invalid_request = "invalid_request"
    not_found = "not_found"
    no_face_detected = "no_face_detected"
    no_garments_found = "no_garments_found"
    mask_out_of_range = "mask_out_of_range"
    classification_failed = "classification_failed"
    no_valid_outfits = "no_valid_outfits"
    gemini_unavailable = "gemini_unavailable"


# ---- Shared thresholds (one source of truth for pipeline, scorer, and tests) ----

IMAGE_LONG_SIDE_PX = 1024      # preprocess resizes the long side to this
MASK_MIN_FRACTION = 0.03       # flat-lay mask smaller than this is an error
MASK_MAX_FRACTION = 0.95       # flat-lay mask larger than this is an error
SEGMENT_MIN_FRACTION = 0.02    # scan regions smaller than this are dropped

MIN_COLORS = 1                 # a plain garment can have a single color
MAX_COLORS = 4
COLOR_MERGE_DELTA_E = 8.0      # merge k-means clusters closer than this (CIEDE2000)
MIN_COLOR_WEIGHT = 0.10        # drop clusters with less than this share of pixels
NEUTRAL_CHROMA_MAX = 12.0      # dominant LCh chroma below this => is_neutral

FORMALITY_MIN = 1              # 1 = loungewear, 3 = smart casual, 5 = formal
FORMALITY_MAX = 5

OUTFIT_MIN_ITEMS = 2           # dress + shoes
OUTFIT_MAX_ITEMS = 4           # top + bottom + shoes + outerwear
REASON_MAX_CHARS = 140
RECOMMEND_MAX_LIMIT = 5
